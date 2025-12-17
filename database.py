import aiosqlite
from datetime import datetime

DB_NAME = "bot_data.db"

async def init_db():
    """Инициализация таблиц базы данных"""
    async with aiosqlite.connect(DB_NAME) as db:
        # Таблица примеров стиля
        await db.execute("""
            CREATE TABLE IF NOT EXISTS style_examples (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                text TEXT
            )
        """)
        # Таблица расписания постов
        await db.execute("""
            CREATE TABLE IF NOT EXISTS schedule (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                post_text TEXT,
                media_file_id TEXT,
                media_type TEXT,
                publish_date DATETIME,
                is_published BOOLEAN DEFAULT 0
            )
        """)
        await db.commit()

# --- ФУНКЦИИ СТИЛЯ ---

async def add_style_example(text):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT INTO style_examples (text) VALUES (?)", (text,))
        await db.commit()

async def clear_style_examples():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("DELETE FROM style_examples")
        await db.commit()

async def get_style_prompt():
    """Возвращает 7 случайных примеров стиля для генерации"""
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT text FROM style_examples ORDER BY RANDOM() LIMIT 7") as cursor:
            rows = await cursor.fetchall()
            if not rows:
                return "Стиль: Живой, авторский блог."
            return "\n---\n".join([r[0] for r in rows])

# --- ФУНКЦИИ РАСПИСАНИЯ И ОЧЕРЕДИ ---

async def add_post_to_schedule(text, pub_date, media_id=None, media_type=None):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "INSERT INTO schedule (post_text, publish_date, media_file_id, media_type, is_published) VALUES (?, ?, ?, ?, 0)", 
            (text, pub_date, media_id, media_type)
        )
        await db.commit()

async def get_due_posts(current_time):
    """Возвращает посты, время которых пришло (для планировщика)"""
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM schedule WHERE is_published = 0 AND publish_date <= ?", 
            (current_time,)
        ) as cursor:
            return await cursor.fetchall()

async def mark_as_published(post_id):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE schedule SET is_published = 1 WHERE id = ?", (post_id,))
        await db.commit()

async def get_last_scheduled_date():
    """Возвращает дату самого последнего запланированного поста (для очереди)"""
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT MAX(publish_date) FROM schedule WHERE is_published = 0") as cursor:
            row = await cursor.fetchone()
            if row and row[0]:
                try:
                    return datetime.fromisoformat(str(row[0]))
                except:
                    # Если формат даты отличается, пробуем стандартный SQL
                    try:
                        return datetime.strptime(str(row[0]), "%Y-%m-%d %H:%M:%S")
                    except:
                        return None
            return None

async def get_all_pending_posts():
    """Возвращает все посты в очереди (для команды /queue)"""
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM schedule WHERE is_published = 0 ORDER BY publish_date ASC") as cursor:
            return await cursor.fetchall()

async def delete_post(post_id):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("DELETE FROM schedule WHERE id = ?", (post_id,))
        await db.commit()

# --- ФУНКЦИЯ ДЛЯ ПАМЯТИ (Именно её не хватало!) ---

async def get_recent_generated_posts(limit=10):
    """
    Возвращает тексты последних постов из базы (включая опубликованные и запланированные).
    Нужно для того, чтобы Gemini не повторял сюжеты.
    """
    async with aiosqlite.connect(DB_NAME) as db:
        # Берем последние записи по ID (самые свежие)
        async with db.execute("SELECT post_text FROM schedule ORDER BY id DESC LIMIT ?", (limit,)) as cursor:
            rows = await cursor.fetchall()
            if not rows:
                return "История пуста."
            
            # Обрезаем тексты, чтобы не забивать контекст (первые 200 символов поста)
            return "\n---\n".join([str(r[0])[:200] + "..." for r in rows])