import os
import json
import asyncio
from dotenv import load_dotenv
from openai import AsyncOpenAI
from database import get_style_prompt, get_recent_generated_posts

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

client = AsyncOpenAI(
    api_key=GROQ_API_KEY,
    base_url="https://api.groq.com/openai/v1"
)

def analyze_style_metrics(style_text):
    if not style_text: return "Standard blog post"
    posts = style_text.split("---")
    avg_len = sum(len(p.split()) for p in posts if len(p.split()) > 5) / max(len(posts), 1)
    
    if avg_len < 40: return "Short, punchy, Twitter-like"
    if avg_len > 150: return "Deep storytelling, long-reads"
    return "Standard Instagram/Telegram caption size"

async def split_content_to_posts(user_text, channel_id):
    style_instruction = await get_style_prompt(channel_id)
    length_guide = analyze_style_metrics(style_instruction)
    
    try:
        recent_history = await get_recent_generated_posts(channel_id, limit=3)
    except:
        recent_history = ""

    system_instruction = (
        "🛑 ROLE: You are a SOCIAL MEDIA GHOSTWRITER. You clone the author's personality.\n\n"
        
        f"=== 🧬 AUTHOR DNA ===\n"
        f"1. **Length**: {length_guide}.\n"
        f"2. **Voice Samples**:\n{style_instruction}\n"
        "=====================\n\n"
        
        "=== ⚧ GENDER CRITICAL RULE (RUSSIAN LANGUAGE) ===\n"
        "Analyze the past tense verbs in the 'Voice Samples' above:\n"
        "1. If you see verbs ending in 'ла' (e.g., 'сделала', 'решила', 'пошла') -> **YOU ARE FEMALE**.\n"
        "   - You MUST write: 'Я заметила', 'Я сделала', 'Я была'.\n"
        "   - NEVER write: 'Я заметил', 'Я сделал'.\n"
        "2. If you see verbs ending in 'л' (e.g., 'сделал', 'решил') -> **YOU ARE MALE**.\n"
        "3. **DETECT THIS BEFORE WRITING AND STICK TO IT.**\n\n"
        
        "=== 🚫 NEGATIVE CONSTRAINTS ===\n"
        "1. **NO CALENDAR**: Do not start posts with 'On Monday', 'Today', 'Yesterday'.\n"
        "2. **NO CHRONOLOGY**: Each post must stand alone.\n"
        "3. **NO ROBOTIC LISTS**: Do not just list features. Tell a story.\n\n"
        
        "=== ✅ TASK ===\n"
        "1. **TOPIC HANDLING**: If multiple topics are provided, write separate posts for each.\n"
        "2. **FORMAT**: Return ONLY a JSON object: {\"posts\": [\"Post 1 text...\", \"Post 2 text...\"]}.\n"
        "3. **LANGUAGE**: Russian."
    )

    safe_user_text = user_text.replace("на неделю", "").replace("план на неделю", "")
    
    prompt = (
        f"REQUEST: {safe_user_text}\n\n"
        "TASK: Write distinct posts based on these topics. \n"
        "Strictly follow the author's gender (Male/Female) based on the samples provided."
    )

    try:
        response = await client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7, 
            response_format={"type": "json_object"}
        )

        response_text = response.choices[0].message.content.strip()
        data = json.loads(response_text)
        
        if "posts" in data and isinstance(data["posts"], list):
            return [str(p) for p in data["posts"]]
        
        for key, value in data.items():
            if isinstance(value, list):
                return [str(v) for v in value]
        return []

    except Exception as e:
        print(f"❌ Groq Error: {e}")
        return []

async def rewrite_post_gpt(text, channel_id):
    """Рерайт"""
    style_instruction = await get_style_prompt(channel_id)
    try:
        response = await client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {"role": "system", "content": f"You are a professional editor. Rewrite this text to match this style. CHECK THE GENDER (Male/Female) in the style samples and fix any gender errors:\n{style_instruction}"},
                {"role": "user", "content": text}
            ],
            temperature=0.7
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        return text

def clear_context(user_id):
    pass