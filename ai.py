"""
ai.py: AI utilities for generating greeting text and images via OpenAI.
Includes improved error handling, retry logic, and type hints.
"""

import random
import asyncio
from typing import Optional

import openai

from environ import OPENAI_API_KEY, IMAGE_SIZE
from log import logger

# Set the OpenAI API key
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
# 🧠 Generate AI Greeting Text
# ╚════════════════════════════════════════════════════════════════════╝
async def generate_greeting_text() -> str:
    """
    Uses OpenAI ChatCompletion to generate a creative greeting message.
    Handles token overflow errors gracefully.
    """
    system_prompt = (
        "You are a character who announces daily schedules in a creative, "
        "entertaining way."
    )
    persona = random.choice(PERSONAS)
    user_prompt = random.choice(GREETING_PROMPTS)

    logger.debug(f"[ai.py] Using persona: {persona}")
    logger.debug(f"[ai.py] Chosen user prompt: {user_prompt}")

    try:
        response = await openai.ChatCompletion.acreate(
            model="gpt-4",
            messages=[
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": f"{user_prompt}\nStay in character as {persona}."
                }
            ],
            temperature=0.8,
            max_tokens=150
        )
        message = response["choices"][0]["message"]["content"].strip()
        logger.debug("[ai.py] Successfully generated greeting text.")
        return message

    except openai.error.InvalidRequestError as e:
        if "maximum context length" in str(e):
            logger.warning("[ai.py] Prompt too long. Retrying with shorter prompt.")
            try:
                # Retry with trimmed persona and prompt
                short_persona = persona[:80]
                short_prompt = user_prompt[:120]
                response = await openai.ChatCompletion.acreate(
                    model="gpt-4",
                    messages=[
                        {"role": "system", "content": "You announce daily schedules in a fun way."},
                        {
                            "role": "user",
                            "content": f"{short_prompt}\nAct as {short_persona}."
                        }
                    ],
                    temperature=0.8,
                    max_tokens=120
                )
                message = response["choices"][0]["message"]["content"].strip()
                logger.debug("[ai.py] Successfully recovered after token overflow.")
                return message
            except Exception as retry_e:
                logger.error(f"[ai.py] Retry after token overflow also failed: {retry_e}")
                return "📜 The herald tried again but still stumbled."
        else:
            logger.error(f"[ai.py] ❌ OpenAI text completion failed: {e}")
            return "📜 The herald was speechless today."
    except Exception as e:
        logger.error(f"[ai.py] ❌ Unexpected error in OpenAI call: {e}")
        return "📜 The herald was speechless today."



# ╔════════════════════════════════════════════════════════════════════╗
# 🎨 Generate Image from Text Prompt
# ╚════════════════════════════════════════════════════════════════════╝
async def generate_greeting_image(
    prompt: str,
    file_path: str = "/tmp/dalle-image.png"
) -> Optional[str]:
    """
    Attempts to generate an image using DALL-E and save it locally.
    Returns the local path on success, or None on failure.
    """
    if not prompt:
        prompt = "a fantasy AI calendar assistant greeting the morning with elegance"

    max_retries = 2
    for attempt in range(1, max_retries + 1):
        logger.debug(f"[ai.py] Image generation attempt {attempt} for prompt: '{prompt}'")
        try:
            response = await openai.Image.acreate(
                model="dall-e-3",
                prompt=prompt,
                n=1,
                size=IMAGE_SIZE,
                response_format="url"
            )
            image_url = response["data"][0]["url"]

            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get(image_url) as resp:
                    if resp.status != 200:
                        logger.warning(f"[ai.py] Failed to fetch image (HTTP {resp.status}): {image_url}")
                        return None

                    try:
                        with open(file_path, "wb") as f:
                            f.write(await resp.read())
                        logger.debug(f"[ai.py] Image saved to {file_path}")
                        return file_path
                    except Exception as file_err:
                        logger.error(f"[ai.py] Failed to save image to {file_path}: {file_err}")
                        return None

        except Exception as e:
            logger.error(f"[ai.py] 🎨 Image generation error (attempt {attempt}): {e}")
            if attempt == max_retries:
                logger.error("[ai.py] Max retries reached. Giving up on image generation.")
                return None

    return None

