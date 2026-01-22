import aiosqlite
import uuid
from datetime import datetime

DB_NAME = "bot_data.db"

async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                channel_tg_id TEXT,
                title TEXT
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS style_examples (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id INTEGER,
                text TEXT
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS schedule (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id INTEGER,
                post_text TEXT,
                media_file_id TEXT,
                media_type TEXT,
                publish_date DATETIME,
                is_published BOOLEAN DEFAULT 0
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                is_active BOOLEAN DEFAULT 0,
                activated_at DATETIME
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS promocodes (
                code TEXT PRIMARY KEY,
                created_by INTEGER,
                is_used BOOLEAN DEFAULT 0,
                used_by INTEGER
            )
        """)
        await db.commit()



async def create_promocode(admin_id):
    code = str(uuid.uuid4())[:8].upper()
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT INTO promocodes (code, created_by) VALUES (?, ?)", (code, admin_id))
        await db.commit()
    return code

async def check_user_access(user_id):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT is_active FROM users WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            if row and row[0]:
                return True
    return False

async def activate_user(user_id, code_input):
    code_input = code_input.strip().upper()
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT is_used FROM promocodes WHERE code = ?", (code_input,)) as cursor:
            row = await cursor.fetchone()
            
            if not row:
                return False, "❌ Такого кода не существует."
            if row[0]:
                return False, "❌ Код уже использован."

        await db.execute("UPDATE promocodes SET is_used = 1, used_by = ? WHERE code = ?", (user_id, code_input))

        await db.execute("""
            INSERT INTO users (user_id, is_active, activated_at) 
            VALUES (?, 1, ?) 
            ON CONFLICT(user_id) DO UPDATE SET is_active=1
        """, (user_id, datetime.now()))
        
        await db.commit()
        return True, "✅ Доступ активирован! Добро пожаловать."

async def add_channel(user_id, channel_tg_id, title):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "INSERT INTO channels (user_id, channel_tg_id, title) VALUES (?, ?, ?)",
            (user_id, channel_tg_id, title)
        )
        await db.commit()

async def get_user_channels(user_id):
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM channels WHERE user_id = ?", (user_id,)) as cursor:
            return await cursor.fetchall()

async def get_channel_by_id(channel_db_id):
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM channels WHERE id = ?", (channel_db_id,)) as cursor:
            return await cursor.fetchone()

async def add_style_example(channel_id, text):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT INTO style_examples (channel_id, text) VALUES (?, ?)", (channel_id, text))
        await db.commit()

async def clear_style_examples(channel_id):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("DELETE FROM style_examples WHERE channel_id = ?", (channel_id,))
        await db.commit()

async def get_style_prompt(channel_id):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT text FROM style_examples WHERE channel_id = ? ORDER BY RANDOM() LIMIT 7", (channel_id,)) as cursor:
            rows = await cursor.fetchall()
            if not rows: return ""
            return "\n---\n".join([r[0] for r in rows])

async def add_post_to_schedule(channel_id, text, pub_date, media_id=None, media_type=None):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "INSERT INTO schedule (channel_id, post_text, publish_date, media_file_id, media_type, is_published) VALUES (?, ?, ?, ?, ?, 0)", 
            (channel_id, text, pub_date, media_id, media_type)
        )
        await db.commit()

async def get_due_posts(current_time):
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT s.*, c.channel_tg_id 
            FROM schedule s 
            JOIN channels c ON s.channel_id = c.id 
            WHERE s.is_published = 0 AND s.publish_date <= ?
            """, 
            (current_time,)
        ) as cursor:
            return await cursor.fetchall()

async def mark_as_published(post_id):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE schedule SET is_published = 1 WHERE id = ?", (post_id,))
        await db.commit()

async def get_last_scheduled_date(channel_id):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT MAX(publish_date) FROM schedule WHERE is_published = 0 AND channel_id = ?", (channel_id,)) as cursor:
            row = await cursor.fetchone()
            if row and row[0]:
                try:
                    return datetime.fromisoformat(str(row[0]))
                except:
                    try: return datetime.strptime(str(row[0]), "%Y-%m-%d %H:%M:%S")
                    except: return None
            return None

async def get_all_pending_posts(channel_id):
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM schedule WHERE is_published = 0 AND channel_id = ? ORDER BY publish_date ASC", (channel_id,)) as cursor:
            return await cursor.fetchall()

async def delete_post(post_id):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("DELETE FROM schedule WHERE id = ?", (post_id,))
        await db.commit()

async def get_recent_generated_posts(channel_id, limit=10):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT post_text FROM schedule WHERE channel_id = ? ORDER BY id DESC LIMIT ?", (channel_id, limit)) as cursor:
            rows = await cursor.fetchall()
            if not rows: return "No history yet."
            return "\n---\n".join([str(r[0])[:200] + "..." for r in rows])

async def get_scheduled_post(post_id):
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM schedule WHERE id = ?", (post_id,)) as cursor:
            return await cursor.fetchone()

async def update_scheduled_post_text(post_id, new_text):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE schedule SET post_text = ? WHERE id = ?", (new_text, post_id))
        await db.commit()

async def update_scheduled_post_media(post_id, media_id, media_type):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "UPDATE schedule SET media_file_id = ?, media_type = ? WHERE id = ?", 
            (media_id, media_type, post_id)
        )
        await db.commit()