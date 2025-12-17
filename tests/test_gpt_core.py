import pytest
from unittest.mock import AsyncMock, patch
import gpt_core

@pytest.mark.asyncio
async def test_split_content_empty_response():
    """Тест обработки ошибок API"""
    
    
    with patch("google.generativeai.GenerativeModel") as MockModel:
        mock_instance = MockModel.return_value
       
        mock_instance.generate_content_async = AsyncMock(side_effect=Exception("API Error"))
        
        result = await gpt_core.split_content_to_posts("Тема поста")
        
        
        assert result == []

@pytest.mark.asyncio
async def test_rewrite_post_fallback():
    """Тест рерайта: если API падает, возвращается оригинал"""
    original_text = "Original text"
    
    with patch("google.generativeai.GenerativeModel") as MockModel:
        mock_instance = MockModel.return_value
        mock_instance.generate_content_async = AsyncMock(side_effect=Exception("Fail"))
        
        result = await gpt_core.rewrite_post_gpt(original_text)
        assert result == original_text