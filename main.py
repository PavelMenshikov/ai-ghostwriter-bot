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

# Импорты из локальных модулей
from database import (
    init_db, add_style_example, clear_style_examples, 
    add_post_to_schedule, get_due_posts, mark_as_published, 
    get_last_scheduled_date, get_all_pending_posts, delete_post
)
from gpt_core import split_content_to_posts, rewrite_post_gpt

load_dotenv()
logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN")
try:
    ADMIN_ID = int(os.getenv("ADMIN_ID"))
except:
    ADMIN_ID = None
CHANNEL_ID = os.getenv("CHANNEL_ID")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
scheduler = AsyncIOScheduler()

# Состояния
class ContentGen(StatesGroup):
    learning = State()     
    waiting_for_media = State()

# --- Клавиатуры ---

def get_post_actions_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🖼 Добавить картинку", callback_data="act_attach_media"),
            InlineKeyboardButton(text="🔄 Переписать", callback_data="act_rewrite")
        ],
        [
            InlineKeyboardButton(text="📥 В очередь (Авто)", callback_data="act_queue"),
            InlineKeyboardButton(text="🗑 Удалить", callback_data="act_del")
        ]
    ])

def get_cancel_media_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена загрузки", callback_data="cancel_media")]])

def get_queue_item_keyboard(post_id):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Удалить из плана", callback_data=f"q_del_{post_id}")]
    ])

def get_main_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎓 Обучить стилю", callback_data="btn_learn")],
        [InlineKeyboardButton(text="🗑 Сброс стиля", callback_data="btn_reset")]
    ])

def get_cancel_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="btn_cancel")]])


@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    if ADMIN_ID and message.from_user.id != ADMIN_ID: return
    await state.clear()
    
    welcome_text = (
        "👋 **Твой личный AI-Гострайтер**\n\n"
        "Я пишу посты в твоем стиле. Я понимаю сложные задачи: могу выдать один пост, а могу сразу контент-план на неделю.\n\n"
        "✍️ **Примеры запросов (просто напиши мне):**\n"
        "🔹 _«Напиши пост-знакомство»_ — (Сделаю 1 пост)\n"
        "🔹 _«Напиши 5 вредных советов для новичков»_ — (Сделаю 5 отдельных постов)\n"
        "🔹 _«Расскажи историю про сложного клиента и сделай из неё 3 вывода»_ — (Разобью на логические части)\n\n"
        "👇 **Просто отправь мне тему или задачу:**"
    )
    
    await message.answer(
        welcome_text,
        reply_markup=get_main_keyboard(), 
        parse_mode="Markdown"
    )

@dp.message(Command("queue"))
async def cmd_view_queue(message: types.Message):
    if ADMIN_ID and message.from_user.id != ADMIN_ID: return

    posts = await get_all_pending_posts()
    if not posts:
        await message.answer("📭 Очередь пуста.")
        return

    await message.answer(f"📅 **В очереди {len(posts)} постов:**")
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

        icon = "🖼" if media else "📝"
        preview = p_text[:100] + "..." if len(p_text) > 100 else p_text
        
        await message.answer(
            f"{icon} 🕒 <b>{date_str}</b>\n{preview}", 
            reply_markup=get_queue_item_keyboard(pid),
            parse_mode="HTML"
        )

@dp.message(Command("learn"))
async def cmd_learn(message: types.Message, state: FSMContext):
    """Команда для обучения (дублирует кнопку)"""
    if ADMIN_ID and message.from_user.id != ADMIN_ID: return
    await state.set_state(ContentGen.learning)
    await message.answer("🎓 Перешли мне посты автора (текст). Я запомню стиль.", reply_markup=get_cancel_keyboard())

@dp.message(Command("reset"))
async def cmd_reset(message: types.Message):
    """Команда сброса стиля"""
    if ADMIN_ID and message.from_user.id != ADMIN_ID: return
    await clear_style_examples()
    await message.answer("🗑 Стиль сброшен. Бот чист.")


@dp.callback_query(F.data == "btn_learn")
async def cb_learn(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(ContentGen.learning)
    await callback.message.edit_text("🎓 Перешли посты автора.", reply_markup=get_cancel_keyboard())

@dp.message(ContentGen.learning)
async def process_learning(message: types.Message):
    if message.text or message.caption:
        text = message.text or message.caption
        await add_style_example(text)
        await message.answer("✅ Запомнил.")
    else:
        await message.answer("Это не текст.")

@dp.callback_query(F.data == "btn_reset")
async def cb_reset(callback: types.CallbackQuery):
    await clear_style_examples()
    await callback.answer("Стиль сброшен.", show_alert=True)

@dp.callback_query(F.data == "btn_cancel")
async def cb_cancel(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("Готов к работе.", reply_markup=get_main_keyboard())



@dp.message(F.text & ~F.text.startswith("/"))
async def handle_text_generation(message: types.Message):
    if ADMIN_ID and message.from_user.id != ADMIN_ID: return
    
    status = await message.answer("💎 Gemini пишет...")
    posts = await split_content_to_posts(message.text)
    await status.delete()
    
    if not posts:
        await message.answer("❌ Не удалось сгенерировать контент.")
        return

    await message.answer(f"✅ Готово! Постов: {len(posts)}")
    for post_text in posts:
        await message.answer(post_text, reply_markup=get_post_actions_keyboard(), parse_mode=None)

# --- РАБОТА С МЕДИА ---

@dp.callback_query(F.data == "act_attach_media")
async def cb_attach_media_start(callback: types.CallbackQuery, state: FSMContext):
    text = callback.message.text or callback.message.caption
    
    await state.update_data(
        draft_text=text,
        draft_msg_id=callback.message.message_id,
        draft_chat_id=callback.message.chat.id
    )
    
    await state.set_state(ContentGen.waiting_for_media)
    await callback.message.answer(
        "📸 **Отправь мне фото или видео**.", 
        reply_markup=get_cancel_media_keyboard(), 
        parse_mode="Markdown"
    )
    await callback.answer()

@dp.callback_query(F.data == "cancel_media")
async def cb_cancel_media(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.delete()
    await callback.answer("Отмена")

@dp.message(ContentGen.waiting_for_media)
async def process_media_upload(message: types.Message, state: FSMContext):
    data = await state.get_data()
    draft_text = data.get("draft_text")
    old_msg_id = data.get("draft_msg_id")
    chat_id = data.get("draft_chat_id")
    
    file_id = None
    media_type = None

    if message.photo:
        file_id = message.photo[-1].file_id
        media_type = "photo"
    elif message.video:
        file_id = message.video.file_id
        media_type = "video"
    elif message.document and message.document.mime_type and 'image' in message.document.mime_type:
        file_id = message.document.file_id
        media_type = "photo"
    
    if not file_id:
        await message.answer("❌ Это не фото/видео.")
        return

    # Удаляем старые сообщения для чистоты
    try: await bot.delete_message(chat_id, old_msg_id)
    except: pass
    try: await message.delete()
    except: pass

    # Отправляем обновленный пост
    if media_type == "photo":
        await bot.send_photo(chat_id, photo=file_id, caption=draft_text, reply_markup=get_post_actions_keyboard(), parse_mode=None)
    elif media_type == "video":
        await bot.send_video(chat_id, video=file_id, caption=draft_text, reply_markup=get_post_actions_keyboard(), parse_mode=None)
    
    await state.clear()

# --- ДЕЙСТВИЯ С ПОСТАМИ ---

@dp.callback_query(F.data == "act_del")
async def cb_act_del(callback: types.CallbackQuery):
    await callback.message.delete()
    await callback.answer("Удалено")

@dp.callback_query(F.data == "act_rewrite")
async def cb_act_rewrite(callback: types.CallbackQuery):
    if callback.message.photo or callback.message.video:
        await callback.answer("Сначала перепиши текст, потом добавляй картинку (ограничение API).", show_alert=True)
        return

    await callback.answer("Переписываю...", show_alert=False)
    original_text = callback.message.text
    new_text = await rewrite_post_gpt(original_text)
    if new_text != original_text:
        await callback.message.edit_text(new_text, reply_markup=get_post_actions_keyboard())
    else:
        await callback.answer("Не удалось.", show_alert=True)

@dp.callback_query(F.data == "act_queue")
async def cb_act_queue(callback: types.CallbackQuery):
    if not CHANNEL_ID:
        await callback.answer("❌ Нет CHANNEL_ID в .env", show_alert=True)
        return

    text = callback.message.text or callback.message.caption
    media_id = None
    media_type = None
    
    if callback.message.photo:
        media_id = callback.message.photo[-1].file_id
        media_type = "photo"
    elif callback.message.video:
        media_id = callback.message.video.file_id
        media_type = "video"

    # Расчет времени
    last_date = await get_last_scheduled_date()
    now = datetime.now()
    
    base_target = now + timedelta(days=1)
    base_target = base_target.replace(hour=12, minute=0, second=0, microsecond=0)
    
    if last_date and last_date > now:
        next_date = last_date + timedelta(days=1)
        next_date = next_date.replace(hour=12, minute=0, second=0, microsecond=0)
    else:
        next_date = base_target

    await add_post_to_schedule(text, next_date, media_id, media_type)
    
    date_str = next_date.strftime("%d.%m.%Y %H:%M")
    
    # Визуальное подтверждение
    final_text = f"✅ **В очереди!**\n📅 {date_str}\n\n{text}"
    if media_type:
        await callback.message.edit_caption(caption=final_text, parse_mode="Markdown", reply_markup=None)
    else:
        await callback.message.edit_text(final_text, parse_mode="Markdown", reply_markup=None)
        
    await callback.answer(f"Добавлено на {date_str}")

@dp.callback_query(F.data.startswith("q_del_"))
async def cb_queue_del(callback: types.CallbackQuery):
    post_id = int(callback.data.split("_")[2])
    await delete_post(post_id)
    await callback.message.delete()
    await callback.answer("Удалено")

# --- ПЛАНИРОВЩИК ---

async def scheduler_job():
    now = datetime.now()
    posts = await get_due_posts(now)
    for post in posts:
        pid = post['id']
        text = post['post_text']
        media_id = post['media_file_id']
        media_type = post['media_type']
        try:
            if CHANNEL_ID:
                if media_id:
                    if media_type == 'photo': await bot.send_photo(CHANNEL_ID, photo=media_id, caption=text, parse_mode="Markdown")
                    elif media_type == 'video': await bot.send_video(CHANNEL_ID, video=media_id, caption=text, parse_mode="Markdown")
                else:
                    await bot.send_message(CHANNEL_ID, text, parse_mode="Markdown")
            await mark_as_published(pid)
        except Exception:
            # Fallback без markdown
            try:
                if media_id:
                     if media_type == 'photo': await bot.send_photo(CHANNEL_ID, media_id, caption=text)
                     else: await bot.send_video(CHANNEL_ID, media_id, caption=text)
                else: await bot.send_message(CHANNEL_ID, text)
                await mark_as_published(pid)
            except: pass

async def main():
    await init_db()
    
    # УСТАНОВКА МЕНЮ КОМАНД
    commands = [
        BotCommand(command="start", description="🚀 Новый пост"),
        BotCommand(command="queue", description="📅 План постов"),
        BotCommand(command="learn", description="🎓 Дообучить стилю"),
        BotCommand(command="reset", description="🗑 Сброс стиля")
    ]
    await bot.set_my_commands(commands)
    
    scheduler.add_job(scheduler_job, "interval", minutes=1)
    scheduler.start()
    
    await bot.delete_webhook(drop_pending_updates=True)
    print("🤖 Бот запущен! Меню обновлено.")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())