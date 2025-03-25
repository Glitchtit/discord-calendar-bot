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
        f"OwO~! It's {today} and we got some steamy scheduluwus coming up: {event_summary}~ ✨ "
        f"Write a depraved, furry-anime hybrid greeting inspired by the 'owo what's this' meme, "
        f"like something a feral Discord mod in a maid outfit would purr. React to the events in an overly flirty, slightly unhinged way. "
        f"Use kawaii language like 'nya~', 'uwu', and 'sugoii~', and sprinkle in hearts or emoticons (✧ω✧). "
        f"Keep it under 40 words and make it sound like they’re about to put on their tail plug before breakfast."
    )


    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "You're a painfully horny, uwu-fied furry anime assistant who speaks in maximum cringe."},
            {"role": "user", "content": prompt},
        ],
        max_completion_tokens=100,
    )

    return response.choices[0].message.content.strip()


def generate_image_prompt():
    today = datetime.now().strftime("%A")
    return (
        f"A hyper-kawaii, overly detailed, blushing anthropomorphic furry anime character with huge sparkling eyes, "
        f"fox ears, a floofy tail, and thigh-high socks, stretching seductively with a steaming cup of strawberry tea on a cozy {today} morning. "
        f"The scene is drenched in pastel sparkles, hearts, floating chibi emojis, and soft lighting. "
        f"The character is surrounded by plushies, posters of magical wolf-dragon hybrids, and radiates 'I'm in heat but it's wholesome' energy. "
        f"Cringe levels are maximum. Make it look like it belongs on a dakimakura or the homepage of a long-forgotten DeviantArt RP forum."
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
