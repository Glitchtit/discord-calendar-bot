import os
import requests
from datetime import datetime
from openai import OpenAI
from dateutil import tz


# Load environment variables
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

client = OpenAI(api_key=OPENAI_API_KEY)

def generate_greeting(event_titles: list[str]):
    today = datetime.now().strftime("%A, %B %d")

    # Join event titles into a string prompt
    event_summary = ", ".join(event_titles) if event_titles else "no special events"

    prompt = (
        f"Today is {today} and the schedule includes: {event_summary}. "
        f"Write a degenerate but appropriate, furry/anime-style greeting inspired by the 'owo what's this' meme, "
        f"that mentions or reacts to some of those events in a horny way. "
        f"Use language like 'uwu', 'nya~', or 'hewwo' and keep it under 40 words. "
        f"Sound like a horny but appropriate anime/furry assistant."
    )

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "You're a degenerate but appropriate furry anime assistant. Speak in an uwu/kawaii style."},
            {"role": "user", "content": prompt},
        ],
        max_completion_tokens=60,
    )

    return response.choices[0].message.content.strip()


def generate_image_prompt():
    today = datetime.now().strftime("%A")
    return (
        f"A degenerate but appropriate anime-style furry character stretching with a cup of tea on a {today} morning, "
        f"in soft pastel colors, with sparkles and a warm glowing vibe, kawaii aesthetic, while looking like they are in heat."
    )

def generate_image():
    image_prompt = generate_image_prompt()

    response = client.images.generate(
        model="dall-e-3",
        prompt=image_prompt,
        size="1024x1024",
        quality="standard",
        n=1
    )
    return response.data[0].url

def post_greeting_to_discord(events: list[dict]):
    if not DISCORD_WEBHOOK_URL:
        print("[DEBUG] No DISCORD_WEBHOOK_URL set.")
        return

    event_titles = [e.get("summary", "mystewious event~") for e in events]
    greeting = generate_greeting(event_titles)
    image_url = generate_image()

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

    resp = requests.post(DISCORD_WEBHOOK_URL, json=payload)
    if resp.status_code not in [200, 204]:
        print(f"[DEBUG] Discord greeting post failed: {resp.status_code} {resp.text}")
    else:
        print("[DEBUG] Discord greeting post successful.")


if __name__ == "__main__":
    post_greeting_to_discord()
