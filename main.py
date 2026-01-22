import asyncio
import os
import logging
from datetime import datetime, timedelta
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, BotCommand
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from database import (
    init_db, add_style_example, clear_style_examples, 
    add_post_to_schedule, get_due_posts, mark_as_published, 
    get_last_scheduled_date, get_all_pending_posts, delete_post,
    add_channel, get_user_channels, get_channel_by_id,
    create_promocode, check_user_access, activate_user,
    get_scheduled_post, update_scheduled_post_text, update_scheduled_post_media
)
from gpt_core import split_content_to_posts, rewrite_post_gpt

load_dotenv()
logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = [5705636679, 1561345883]

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
scheduler = AsyncIOScheduler()

class BotStates(StatesGroup):
    waiting_for_promo = State()
    
    waiting_for_channel_id = State()
    waiting_for_channel_title = State()
    
    learning_select_channel = State()
    learning_input = State()
    
    generation_select_channel = State()

    queue_waiting_for_media = State()


def get_main_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить канал", callback_data="cmd_add_channel")],
        [InlineKeyboardButton(text="🎓 Обучить бота", callback_data="cmd_learn_start")],
        [InlineKeyboardButton(text="📅 Мои очереди", callback_data="cmd_queue_list")]
    ])

def get_channels_keyboard(channels, prefix):
    kb = []
    for ch in channels:
        kb.append([InlineKeyboardButton(text=f"📢 {ch['title']}", callback_data=f"{prefix}{ch['id']}")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

def get_post_actions_keyboard(channel_id):
    """Клавиатура для ТОЛЬКО ЧТО сгенерированного поста"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🖼 Картинка", callback_data=f"act_media_{channel_id}"),
            InlineKeyboardButton(text="🔄 Переписать", callback_data=f"act_rewrite_{channel_id}")
        ],
        [
            InlineKeyboardButton(text="📥 В очередь", callback_data=f"act_queue_{channel_id}"),
            InlineKeyboardButton(text="🗑 Удалить", callback_data="act_del")
        ]
    ])

def get_queue_item_keyboard(post_id):
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🖼 Изм. фото", callback_data=f"q_img_{post_id}"),
            InlineKeyboardButton(text="🔄 Переписать", callback_data=f"q_rew_{post_id}")
        ],
        [InlineKeyboardButton(text="❌ Удалить из плана", callback_data=f"q_del_{post_id}")]
    ])

@dp.message(Command("promo"))
async def cmd_promo(message: types.Message):
    if message.from_user.id not in ADMIN_IDS: return
    code = await create_promocode(message.from_user.id)
    await message.answer(f"🎫 Новый промокод:\n`{code}`", parse_mode="Markdown")

@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id
    
    has_access = await check_user_access(user_id)
    if user_id in ADMIN_IDS: has_access = True
        
    if not has_access:
        await message.answer("🔒 **Доступ закрыт.** Введите промокод:")
        await state.set_state(BotStates.waiting_for_promo)
        return

    channels = await get_user_channels(user_id)
    text = "👋 **Привет! Я AI-Гострайтер.**\n"
    
    if not channels:
        text += "❌ **Нет каналов.** Добавь первый:"
    else:
        text += f"✅ Каналов: {len(channels)}.\nПиши тему поста или жми кнопки."

    await message.answer(text, reply_markup=get_main_menu(), parse_mode="Markdown")

@dp.message(BotStates.waiting_for_promo)
async def process_promo(message: types.Message, state: FSMContext):
    success, msg = await activate_user(message.from_user.id, message.text)
    if success:
        await state.clear()
        await message.answer(msg)
        await cmd_start(message, state)
    else:
        await message.answer(msg + "\nПопробуйте еще раз:")

@dp.message(Command("queue"))
async def cmd_queue(message: types.Message):
    """Слеш-команда для просмотра очереди"""
    user_id = message.from_user.id
    if user_id not in ADMIN_IDS and not await check_user_access(user_id): return

    channels = await get_user_channels(user_id)
    if not channels:
        await message.answer("❌ Нет каналов.")
        return
        
    await message.answer("📅 Чью очередь смотрим?", reply_markup=get_channels_keyboard(channels, "queue_"))

@dp.callback_query(F.data == "cmd_queue_list")
async def cb_queue_list_btn(callback: types.CallbackQuery):
    channels = await get_user_channels(callback.from_user.id)
    if not channels: return
    await callback.message.edit_text("📅 Чью очередь смотрим?", reply_markup=get_channels_keyboard(channels, "queue_"))

@dp.callback_query(F.data.startswith("queue_"))
async def cb_queue_show(callback: types.CallbackQuery):
    channel_id = int(callback.data.split("_")[1])
    posts = await get_all_pending_posts(channel_id)
    
    if not posts:
        await callback.answer("Очередь пуста 📭", show_alert=True)
        return
        
    await callback.message.answer(f"📅 **Очередь (всего {len(posts)}):**", parse_mode="Markdown")
    for post in posts:
        pid = post['id']
        p_date = post['publish_date']
        p_text = post['post_text']
        media = post['media_file_id']
        
        try:
            if isinstance(p_date, str): dt = datetime.fromisoformat(p_date)
            else: dt = p_date
            date_str = dt.strftime("%d.%m %H:%M")
        except:
            date_str = str(p_date)

        preview = p_text[:150] + "..." if len(p_text) > 150 else p_text

        if media:
             await callback.message.answer_photo(
                media, 
                caption=f"🕒 **{date_str}**\n{preview}",
                reply_markup=get_queue_item_keyboard(pid),
                parse_mode="Markdown"
             )
        else:
            await callback.message.answer(
                f"🕒 **{date_str}**\n{preview}", 
                reply_markup=get_queue_item_keyboard(pid),
                parse_mode="Markdown"
            )
    await callback.answer()

@dp.callback_query(F.data.startswith("q_del_"))
async def cb_queue_delete_item(callback: types.CallbackQuery):
    post_id = int(callback.data.split("_")[2])
    await delete_post(post_id)
    await callback.message.delete()
    await callback.answer("Удалено 🗑")

@dp.callback_query(F.data.startswith("q_rew_"))
async def cb_queue_rewrite(callback: types.CallbackQuery):
    post_id = int(callback.data.split("_")[2])

    post = await get_scheduled_post(post_id)
    if not post:
        await callback.answer("Пост не найден", show_alert=True)
        return

    await callback.answer("Переписываю... (это займет время)")

    new_text = await rewrite_post_gpt(post['post_text'], post['channel_id'])

    await update_scheduled_post_text(post_id, new_text)

    try:
        dt_str = "🕒 Дата публикации" 
        try:
            dt = datetime.fromisoformat(str(post['publish_date']))
            dt_str = f"🕒 **{dt.strftime('%d.%m %H:%M')}**"
        except: pass

        preview = new_text[:150] + "..." if len(new_text) > 150 else new_text
        
        if callback.message.caption:
            await callback.message.edit_caption(
                caption=f"{dt_str}\n{preview}", 
                reply_markup=get_queue_item_keyboard(post_id),
                parse_mode="Markdown"
            )
        else:
            await callback.message.edit_text(
                f"{dt_str}\n{preview}", 
                reply_markup=get_queue_item_keyboard(post_id),
                parse_mode="Markdown"
            )
    except Exception as e:
        print(f"Error editing message: {e}")

@dp.callback_query(F.data.startswith("q_img_"))
async def cb_queue_image_start(callback: types.CallbackQuery, state: FSMContext):
    post_id = int(callback.data.split("_")[2])
    
    await state.set_state(BotStates.queue_waiting_for_media)
    await state.update_data(editing_post_id=post_id, editing_msg_id=callback.message.message_id)
    
    await callback.message.reply("📸 **Отправь мне новое фото для этого поста.**", parse_mode="Markdown")
    await callback.answer()

@dp.message(BotStates.queue_waiting_for_media)
async def cb_queue_image_finish(message: types.Message, state: FSMContext):
    data = await state.get_data()
    post_id = data.get('editing_post_id')
    
    if not message.photo:
        await message.answer("❌ Это не фото. Отмена.")
        await state.clear()
        return

    file_id = message.photo[-1].file_id
 
    await update_scheduled_post_media(post_id, file_id, "photo")
    
    await message.answer("✅ Картинка обновлена! (Нажми /queue чтобы проверить)")
    await state.clear()


@dp.callback_query(F.data == "cmd_add_channel")
async def cb_add_channel(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(BotStates.waiting_for_channel_id)
    await callback.message.edit_text("📝 **Шаг 1:** Скинь @username канала или ID (я должен быть там админом).")

@dp.message(BotStates.waiting_for_channel_id)
async def process_channel_id(message: types.Message, state: FSMContext):
    tg_id = message.text.strip()
    try:
        chat_info = await bot.get_chat(tg_id)
        if chat_info.type != "channel":
            await message.answer("❌ Это не канал.")
            return
    except:
        await message.answer("❌ Не вижу канал. Сделай меня админом!")
        return

    await state.update_data(tg_id=tg_id)
    await state.set_state(BotStates.waiting_for_channel_title)
    await message.answer("📝 **Шаг 2:** Название для бота?")

@dp.message(BotStates.waiting_for_channel_title)
async def process_channel_title(message: types.Message, state: FSMContext):
    data = await state.get_data()
    await add_channel(message.from_user.id, data['tg_id'], message.text)
    await state.clear()
    await message.answer(f"✅ Канал **{message.text}** добавлен!", reply_markup=get_main_menu(), parse_mode="Markdown")

@dp.callback_query(F.data == "cmd_learn_start")
async def cb_learn_start(callback: types.CallbackQuery):
    channels = await get_user_channels(callback.from_user.id)
    if not channels: return
    await callback.message.edit_text("🎓 Какой канал обучаем?", reply_markup=get_channels_keyboard(channels, "learn_"))

@dp.callback_query(F.data.startswith("learn_"))
async def cb_learn_select(callback: types.CallbackQuery, state: FSMContext):
    channel_id = int(callback.data.split("_")[1])
    channel = await get_channel_by_id(channel_id)
    await state.update_data(active_channel_id=channel_id)
    await state.set_state(BotStates.learning_input)
    await callback.message.edit_text(f"🎓 Кидай посты для **{channel['title']}**. Я запомню стиль.", reply_markup=None)

@dp.message(BotStates.learning_input)
async def process_learning_text(message: types.Message, state: FSMContext):
    data = await state.get_data()
    text = message.text or message.caption
    if text:
        try:
            await add_style_example(data['active_channel_id'], text)
            await message.react([types.ReactionTypeEmoji(emoji="👍")])
        except: pass


@dp.message(F.text & ~F.text.startswith("/"))
async def handle_text_generation_init(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    if user_id not in ADMIN_IDS and not await check_user_access(user_id):
        await message.answer("🔒 Нужен промокод.")
        await state.set_state(BotStates.waiting_for_promo)
        return

    channels = await get_user_channels(user_id)
    if not channels: return

    await state.update_data(prompt_text=message.text)
    if len(channels) == 1:
        await run_generation(message, channels[0]['id'], message.text)
    else:
        await message.answer("Для какого канала?", reply_markup=get_channels_keyboard(channels, "gen_"))

@dp.callback_query(F.data.startswith("gen_"))
async def cb_gen_select(callback: types.CallbackQuery, state: FSMContext):
    channel_id = int(callback.data.split("_")[1])
    data = await state.get_data()
    await callback.message.delete()
    await run_generation(callback.message, channel_id, data.get('prompt_text'))

async def run_generation(message, channel_id, text):
    status = await message.answer("⏳ Groq пишет...")
    posts = await split_content_to_posts(text, channel_id)
    await status.delete()
    
    if not posts:
        await message.answer("❌ Ошибка API.")
        return

    await message.answer("✅ Готово:")
    for post in posts:
        await message.answer(post, reply_markup=get_post_actions_keyboard(channel_id))

@dp.callback_query(F.data.startswith("act_queue_"))
async def cb_queue_add(callback: types.CallbackQuery):
    channel_id = int(callback.data.split("_")[2])
    text = callback.message.text or callback.message.caption
    
    last_date = await get_last_scheduled_date(channel_id)
    now = datetime.now()
    target = (now + timedelta(days=1)).replace(hour=12, minute=0, second=0)
    
    if last_date and last_date > now:
        target = last_date + timedelta(days=1)
        target = target.replace(hour=12, minute=0, second=0)
        
    await add_post_to_schedule(channel_id, text, target)
    await callback.message.edit_text(f"✅ **В очереди на {target.strftime('%d.%m %H:%M')}**\n\n{text}", parse_mode="Markdown")

@dp.callback_query(F.data.startswith("act_rewrite_"))
async def cb_rewrite(callback: types.CallbackQuery):
    channel_id = int(callback.data.split("_")[2])
    original = callback.message.text
    await callback.answer("Думаю...")
    new_text = await rewrite_post_gpt(original, channel_id)
    if new_text != original:
        await callback.message.edit_text(new_text, reply_markup=get_post_actions_keyboard(channel_id))

@dp.callback_query(F.data == "act_del")
async def cb_del(callback: types.CallbackQuery):
    await callback.message.delete()

async def scheduler_job():
    now = datetime.now()
    posts = await get_due_posts(now)
    for post in posts:
        try:
            await bot.send_message(post['channel_tg_id'], post['post_text'])
            await mark_as_published(post['id'])
        except Exception as e:
            print(f"❌ Ошибка публикации: {e}")

async def main():
    await init_db()
    
    commands = [
        BotCommand(command="start", description="🚀 Меню"),
        BotCommand(command="queue", description="📅 Очередь"),
        BotCommand(command="promo", description="🎟 Админ")
    ]
    await bot.set_my_commands(commands)
    
    scheduler.add_job(scheduler_job, "interval", minutes=1)
    scheduler.start()
    
    await bot.delete_webhook(drop_pending_updates=True)
    print("🤖 Бот запущен (Access Control: ON)")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())