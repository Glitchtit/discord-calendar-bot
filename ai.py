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
    Uses OpenAI ChatCompletion to generate a creative greeting message,
    combining a randomly chosen user prompt with a persona.

    Returns:
        A string containing the greeting text. If the OpenAI API call fails,
        returns a fallback string.
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
    except Exception as e:
        logger.error(f"[ai.py] ❌ OpenAI text completion failed: {e}")
        return "📜 The herald was speechless today."


# ╔════════════════════════════════════════════════════════════════════╗
# 🎨 Generate Image from Text Prompt
# ╚════════════════════════════════════════════════════════════════════╝
async def generate_greeting_image(
    prompt: str,
    file_path: str = "/tmp/dalle-image.png"
) -> Optional[str]:
    """
    Given a textual prompt, attempts to generate an image using OpenAI's DALL-E.
    Downloads the image to the specified file path and returns that path.

    Args:
        prompt: Text prompt to be used for image generation.
        file_path: Path to save the generated image. Default is /tmp/dalle-image.png.

    Returns:
        The file path if successful, otherwise None on error.
    """
    if not prompt:
        prompt = "a fantasy AI calendar assistant greeting the morning with elegance"

    # Simple retry mechanism (e.g., 2 attempts)
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

            # Download and save image
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get(image_url) as resp:
                    if resp.status != 200:
                        logger.warning(f"[ai.py] Failed to fetch image from URL: {image_url}")
                        return None

                    with open(file_path, "wb") as f:
                        f.write(await resp.read())

            logger.debug(f"[ai.py] Image downloaded successfully to {file_path}")
            return file_path

        except Exception as e:
            logger.error(f"[ai.py] 🎨 Failed to generate/download image (attempt {attempt}): {e}")
            # Retry on next loop if attempts remain
            if attempt == max_retries:
                logger.error("[ai.py] Max retries reached. Giving up on image generation.")
                return None

    # If for some reason we exit the loop without returning, return None
    return None
