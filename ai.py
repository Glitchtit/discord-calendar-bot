import random
import openai
import asyncio

from environ import OPENAI_API_KEY, IMAGE_SIZE
from log import logger

openai.api_key = OPENAI_API_KEY

# ╔════════════════════════════════════════════════════════════════════╗
# 🤖 Greeting Prompt Templates & Personas
# ╚════════════════════════════════════════════════════════════════════╝
GREETING_PROMPTS = [
    "A mysterious AI scribe welcomes the realm to a new day.",
    "A cheerful bard announces the start of a productive day.",
    "A futuristic assistant prepares the calendar for the adventurers.",
    "A cyberpunk oracle forecasts the schedule with poetic flair.",
    "A steampunk automaton delivers today's scrolls with precision gears."
]

PERSONAS = [
    "A wise old mage with a flair for calendar magic.",
    "A futuristic holographic AI companion.",
    "A royal herald from a fantasy kingdom.",
    "A charismatic robot who loves productivity.",
    "A bard who turns calendars into poems."
]

# ╔════════════════════════════════════════════════════════════════════╗
# 🧠 Generate Text Completion Prompt (Greeting)
# ╚════════════════════════════════════════════════════════════════════╝
async def generate_greeting_text() -> str:
    system_prompt = "You are a character who announces daily schedules in a creative and entertaining way."
    persona = random.choice(PERSONAS)
    user_prompt = random.choice(GREETING_PROMPTS)

    logger.debug(f"[ai.py] Using persona: {persona}")
    logger.debug(f"[ai.py] Prompt: {user_prompt}")

    try:
        response = await openai.ChatCompletion.acreate(
            model="gpt-4",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"{user_prompt}\nStay in character as {persona}."}
            ],
            temperature=0.8,
            max_tokens=150
        )
        message = response["choices"][0]["message"]["content"].strip()
        return message
    except Exception as e:
        logger.error(f"❌ OpenAI text completion failed: {e}")
        return "📜 The herald was speechless today."

# ╔════════════════════════════════════════════════════════════════════╗
# 🎨 Generate Image Prompt from Text
# ╚════════════════════════════════════════════════════════════════════╝
async def generate_greeting_image(prompt: str, file_path: str = "/tmp/dalle-image.png") -> str | None:
    if not prompt:
        prompt = "a fantasy AI calendar assistant greeting the morning with elegance"
    try:
        logger.debug(f"[ai.py] Requesting image with prompt: {prompt}")
        response = await openai.Image.acreate(
            model="dall-e-3",
            prompt=prompt,
            n=1,
            size=IMAGE_SIZE,
            response_format="url"
        )
        image_url = response["data"][0]["url"]

        # Download and save image
        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.get(image_url) as resp:
                if resp.status != 200:
                    logger.warning(f"[ai.py] Failed to fetch image from URL: {image_url}")
                    return None
                with open(file_path, "wb") as f:
                    f.write(await resp.read())
        return file_path
    except Exception as e:
        logger.error(f"🎨 Failed to generate or download image: {e}")
        return None
