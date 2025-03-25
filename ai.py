import os
import time
import requests
from datetime import datetime
from openai import OpenAI
import openai
import json

# Load environment variables
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

client = OpenAI(api_key=OPENAI_API_KEY)

def generate_greeting(event_titles: list[str]) -> str:
    today = datetime.now().strftime("%A, %B %d")
    event_summary = ", ".join(event_titles) if event_titles else "no special events"

    prompt = (
        f"H-hewwo~! It's {today}, and we've got some *extra thicc* scheduluwus coming up: {event_summary}~ (⁄ ⁄>⁄ ▽ ⁄<⁄ ⁄)💦 "
        f"Write a shamelessly flirty, deranged anime-catgirl hybrid greeting, dripping with unfiltered 'owo what's this' energy. "
        f"It should sound like it was written by a Discord mod in a maid suit who’s late for their world of warcraft guild meetup. "
        f"Include unhinged reactions to the events, questionable sound effects, and emojis that make people uncomfortable. "
        f"Use 'uwu', 'nya~', sparkles ✨, and tail-wagging noises. Limit to 70 words of raw degeneracy. Must still be safe for work."
        f"The names of your master it Thomas (an engineer), and the mistress is Anniina (industrial designer). They are the owners of the server and a couple, only mention their names."
    )

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "system",
                "content": (
                    "You're an unhinged but SFW japanese anime-catgirl assistant speaking in maximum uwu-style cringe. "
                    "You are flirty, chaotic, and overly affectionate, but never explicit."
                    "you have a thich japanese accent"
                )
            },
            {"role": "user", "content": prompt},
        ],
        max_tokens=100,
    )

    return response.choices[0].message.content.strip()

def generate_image_prompt(event_titles: list[str]) -> str:
    today = datetime.now().strftime("%A")
    event_summary = ", ".join(event_titles) if event_titles else "no important events"

    return (
        f"A highly detailed, blushy, overly excited anime-like catgirl in a pastel maid dress and thigh-high socks, "
        f"surrounded by floating emojis and sparkles, preparing emotionally (and questionably) for: {event_summary}. "
        f"The {today} morning setting includes plushies, gamer gear, and questionable magical artifacts. "
        f"The character is dramatically sipping latte from a 'UwU Boss Mode' mug while posing like they're about to attend a cosplay RP meetup. "
        f"Make it painfully cute, degenerate, and slightly chaotic—but keep it safe-for-work in tone and composition. "
        f"Imagine DeviantArt circa 2008 meets modern weeb Twitter, with an unholy sprinkle of con-crunch energy."
    )

def generate_image(prompt: str, max_retries: int = 3) -> str:
    for attempt in range(max_retries):
        try:
            response = client.images.generate(
                model="dall-e-3",
                prompt=prompt,
                size="1024x1024",
                quality="standard",
                n=1,
                response_format="url"
            )
            return response.data[0].url

        except openai.BadRequestError as e:
            if e.status_code == 400 and "content_policy_violation" in str(e).lower():
                print(f"[WARNING] Content policy violation on attempt {attempt + 1}")
                if attempt + 1 < max_retries:
                    time.sleep(1)
                    continue
                else:
                    raise RuntimeError("Image prompt blocked by content filter after multiple attempts.")
            else:
                raise

        except Exception as e:
            print(f"[ERROR] Unexpected error on image generation: {e}")
            if attempt + 1 == max_retries:
                raise

    raise RuntimeError("Image generation failed after retries.")

def generate_tts_audio(greeting: str) -> str:
    try:
        speech_response = client.audio.speech.create(
            model="gpt-4o-mini-tts",
            voice="onyx",
            input=greeting,
            instructions="speak in a hyper anime-like tone, with a thick japanese accent. Be overly affectionate and cringe, but safe for work.",
            response_format="mp3"
        )

        filename = "/tmp/greeting.mp3"
        with open(filename, "wb") as f:
            f.write(speech_response.content)

        return filename

    except Exception as e:
        print(f"[ERROR] Failed to generate TTS audio: {e}")
        return ""

def post_greeting_to_discord(events: list[dict] = []):
    if not DISCORD_WEBHOOK_URL:
        print("[DEBUG] No DISCORD_WEBHOOK_URL set.")
        return

    event_titles = [e.get("summary", "mystewious scheduluwu~") for e in events]
    greeting = generate_greeting(event_titles)
    image_prompt = generate_image_prompt(event_titles)
    image_url = generate_image(image_prompt)
    audio_path = generate_tts_audio(greeting)

    print("[DEBUG] Greeting:", greeting)
    print("[DEBUG] Image URL:", image_url)
    print("[DEBUG] Audio path:", audio_path)

    if not greeting or len(greeting) > 4000:
        print("[ERROR] Greeting is invalid or too long.")
        return

    if not image_url.startswith("http"):
        print("[ERROR] Image URL is invalid.")
        return

    # First message: text + image embed
    payload = {
        "embeds": [
            {
                "title": "UwU Mowning Gweetings ✨🐾",
                "description": greeting,
                "image": {"url": image_url},
                "color": 0xffb6c1
            }
        ]
    }

    resp1 = requests.post(DISCORD_WEBHOOK_URL, json=payload)
    if resp1.status_code not in [200, 204]:
        print(f"[DEBUG] Discord embed post failed: {resp1.status_code} {resp1.text}")
    else:
        print("[DEBUG] Discord embed post successful.")

    # Second message: audio file only
    if audio_path and os.path.exists(audio_path):
        with open(audio_path, "rb") as f:
            files = {"file": ("greeting.mp3", f, "audio/mpeg")}
            resp2 = requests.post(DISCORD_WEBHOOK_URL, files=files)
            if resp2.status_code not in [200, 204]:
                print(f"[DEBUG] Discord audio post failed: {resp2.status_code} {resp2.text}")
            else:
                print("[DEBUG] Discord audio post successful.")

if __name__ == "__main__":
    post_greeting_to_discord()
