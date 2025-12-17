import os
import json
import asyncio
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold
from dotenv import load_dotenv
from database import get_style_prompt, get_recent_generated_posts

load_dotenv()

genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

safety_settings = {
    HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
}

# Используем модель из вашего списка
MODEL_NAME = "models/gemini-2.0-flash"

async def split_content_to_posts(user_text):
    """
    Генерирует контент с ЖЕСТКИМ следованием роли автора.
    """
    style_instruction = await get_style_prompt()
    
    # Получаем историю, чтобы не повторяться
    try:
        recent_history = await get_recent_generated_posts(limit=10)
    except:
        recent_history = "No history yet."

    system_instruction = (
        "🛑 SYSTEM OVERRIDE: YOU ARE NOT AN AI ASSISTANT. YOU ARE A HUMAN AUTHOR.\n"
        "Your goal is to write posts for your personal Telegram channel. You must pass the 'Turing Test' — the reader must believe a human wrote this.\n\n"
        
        f"=== 🧬 AUTHOR DNA (STYLE & VOICE) ===\n{style_instruction}\n=====================================\n\n"
        
        f"=== 🧠 SHORT TERM MEMORY (DO NOT REPEAT) ===\n{recent_history}\n============================================\n\n"
        
        "=== 💀 STRICT BEHAVIOR RULES ===\n"
        "1. **ABSOLUTE MIMICRY**: Copy the author's sentence length, punctuation quirks (lots of '...' or '!!!'?), emoji usage, and vocabulary depth.\n"
        "2. **NO AI FILLER**: NEVER use phrases like 'In today's world', 'Let's dive in', 'Here is a post', 'Hope you like it'. Just write the content.\n"
        "3. **PERSONALITY**: If the examples show the author is cynical, be cynical. If they are cheerful, be cheerful. Do not be neutrally polite.\n"
        "4. **GENDER CONSISTENCY**: Detect the gender from the examples (verbs like 'сделала' vs 'сделал') and stick to it strictly.\n"
        "5. **STRUCTURE**: Do NOT artificially split one coherent thought into multiple posts. Only split if there are distinct topics.\n"
        "6. **FORMAT**: Output ONLY a JSON array of strings. No markdown outside the JSON."
    )

    # Увеличиваем temperature до 0.85 для большей "человечности" и непредсказуемости
    # Но используем top_p для удержания смысловой нити
    model = genai.GenerativeModel(
        model_name=MODEL_NAME, 
        system_instruction=system_instruction,
        safety_settings=safety_settings,
        generation_config={
            "response_mime_type": "application/json",
            "temperature": 0.85,
            "top_p": 0.95
        }
    )

    try:
        # Добавляем "давление" в сам запрос пользователя
        prompt = (
            f"TASK: Write a post (or posts) based on this topic: '{user_text}'.\n"
            "MODE: Deep Roleplay. Write exactly as THE AUTHOR would write."
        )
        
        response = await model.generate_content_async(prompt)
        posts = json.loads(response.text)
        return posts if isinstance(posts, list) else [str(posts)]
    except Exception as e:
        print(f"Gemini Split Error: {e}")
        return []

async def rewrite_post_gpt(text):
    """Переписывает пост"""
    model = genai.GenerativeModel(model_name=MODEL_NAME, safety_settings=safety_settings)
    
    prompt = (
        "ACT AS THE AUTHOR. Rewrite this post to sound more natural and engaging. "
        "Keep the same meaning but change the wording. "
        f"Text:\n{text}"
    )
    
    try:
        response = await model.generate_content_async(prompt)
        return response.text
    except:
        return text

def clear_context(user_id):
    pass