import os
import time
import requests
from datetime import datetime
from openai import OpenAI
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
        f"Use 'uwu', 'nya~', sparkles ✨, and tail-wagging noises. Limit to 80 words of raw degeneracy. Must still be safe for work."
    )

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {
                "role": "system",
                "content": (
                    "You're an unhinged but SFW japanese anime-catgirl assistant speaking in maximum uwu-style cringe. "
                    "You are flirty, chaotic, and overly affectionate, but never explicit. "
                    "You have a thick japanese accent."
                )
            },
            {"role": "user", "content": prompt},
        ],
        max_tokens=150,
    )

    return response.choices[0].message.content.strip()

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
            image_url = response.data[0].url

            # Download and save the image
            image_response = requests.get(image_url)
            image_response.raise_for_status()

            os.makedirs("/data/art", exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            image_path = f"/data/art/generated_{timestamp}.png"
            with open(image_path, "wb") as f:
                f.write(image_response.content)

            return image_path

        except Exception as e:
            if hasattr(e, "status_code") and e.status_code == 400 and "content_policy_violation" in str(e).lower():
                print(f"[WARNING] Content policy violation on attempt {attempt + 1}")
                if attempt + 1 < max_retries:
                    time.sleep(1)
                    continue
                else:
                    raise RuntimeError("Image prompt blocked by content filter after multiple attempts.")
            else:
                print(f"[ERROR] Unexpected error on image generation: {e}")
                if attempt + 1 == max_retries:
                    raise

    raise RuntimeError("Image generation failed after retries.")

def post_greeting_to_discord(events: list[dict] = []):
    if not DISCORD_WEBHOOK_URL:
        print("[DEBUG] No DISCORD_WEBHOOK_URL set.")
        return

    event_titles = [e.get("summary", "mystewious scheduluwu~") for e in events]
    greeting = generate_greeting(event_titles)
    image_path = generate_image(greeting)

    print("[DEBUG] Greeting:", greeting)
    print("[DEBUG] Image Path:", image_path)

    if not greeting or len(greeting) > 4000:
        print("[ERROR] Greeting is invalid or too long.")
        return

    # Post embed with image
    if image_path and os.path.exists(image_path):
        with open(image_path, "rb") as img_file:
            files = {"file": ("generated_image.png", img_file, "image/png")}
            payload = {
                "embeds": [
                    {
                        "title": "UwU Mowning Gweetings ✨🐾",
                        "description": greeting,
                        "image": {"url": "attachment://generated_image.png"},
                        "color": 0xffb6c1
                    }
                ]
            }
            resp = requests.post(DISCORD_WEBHOOK_URL, data={"payload_json": json.dumps(payload)}, files=files)
            if resp.status_code not in [200, 204]:
                print(f"[DEBUG] Discord embed post failed: {resp.status_code} {resp.text}")
            else:
                print("[DEBUG] Discord embed post successful.")
    else:
        print("[ERROR] Image file is missing or invalid.")

if __name__ == "__main__":
    post_greeting_to_discord()
