import os
import requests
from datetime import datetime
from openai import OpenAI

# Load environment variables
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

client = OpenAI(api_key=OPENAI_API_KEY)

def generate_greeting():
    today = datetime.now().strftime("%A, %B %d")
    prompt = (
        f"Write a playful, furry/anime-style greeting inspired by the 'owo what's this' meme "
        f"for a calendar update on {today}. Use cute language like 'hewwo', 'uwu', or 'nya~', "
        f"and keep it under 30 words. Make it warm, cozy, and silly."
    )

    response = client.chat.completions.create(
        model="gpt-4",
        messages=[
            {"role": "system", "content": "You're a kawaii furry anime assistant, always cheerful and uwu-fied."},
            {"role": "user", "content": prompt},
        ],
        max_tokens=50,
    )
    return response.choices[0].message.content.strip()

def generate_image_prompt():
    today = datetime.now().strftime("%A")
    return (
        f"A cozy anime-style furry character stretching with a cup of tea on a {today} morning, "
        f"in soft pastel colors, with sparkles and a warm glowing vibe, kawaii aesthetic."
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

def post_greeting_to_discord():
    if not DISCORD_WEBHOOK_URL:
        print("[DEBUG] No DISCORD_WEBHOOK_URL set.")
        return

    greeting = generate_greeting()
    image_url = generate_image()

    payload = {
        "embeds": [
            {
                "title": "UwU Mowning Gweetings ✨🐾",
                "description": greeting,
                "image": {"url": image_url},
                "color": 0xffb6c1  # Soft pink kawaii color
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
