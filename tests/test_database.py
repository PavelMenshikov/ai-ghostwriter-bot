import pytest
import os
import aiosqlite
from datetime import datetime
import database


TEST_DB_NAME = "test_bot_data.db"


@pytest.fixture(autouse=True)
async def setup_test_db():
    
    original_db_name = database.DB_NAME
    database.DB_NAME = TEST_DB_NAME
    
 
    if os.path.exists(TEST_DB_NAME):
        os.remove(TEST_DB_NAME)
    
    await database.init_db()
    
    yield
    
    
    if os.path.exists(TEST_DB_NAME):
        os.remove(TEST_DB_NAME)
    database.DB_NAME = original_db_name

@pytest.mark.asyncio
async def test_add_and_get_style():
    """Тест добавления и получения стиля автора"""
    example_text = "Привет, это мой авторский стиль!"
    await database.add_style_example(example_text)
    
    prompt = await database.get_style_prompt()
    assert example_text in prompt
    
   
    await database.clear_style_examples()
    prompt_empty = await database.get_style_prompt()
    assert "Стиль: Живой, авторский блог" in prompt_empty

@pytest.mark.asyncio
async def test_schedule_logic():
    """Тест планировщика постов"""
    post_text = "Test Post"
    future_date = datetime(2030, 1, 1, 12, 0, 0)
    
    
    await database.add_post_to_schedule(post_text, future_date)
    
 
    pending = await database.get_all_pending_posts()
    assert len(pending) == 1
    assert pending[0]['post_text'] == post_text
    
   
    past_check = await database.get_due_posts(datetime(2020, 1, 1))
    assert len(past_check) == 0
    
    
    future_check = await database.get_due_posts(datetime(2031, 1, 1))
    assert len(future_check) == 1
    
    
    post_id = pending[0]['id']
    await database.mark_as_published(post_id)
    
   
    pending_after = await database.get_all_pending_posts()
    assert len(pending_after) == 0