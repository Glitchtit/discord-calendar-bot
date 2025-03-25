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
        f"H-hewwo~! It's {today}, and we've got some *extra thicc* scheduluwus coming up: {event_summary}~ (⁄ ⁄>⁄ ▽ ⁄<⁄ ⁄)💦 "
        f"Write a shamelessly flirty, deranged furry-anime hybrid greeting, dripping with unfiltered 'owo what's this' energy. "
        f"It should sound like it was written by a Discord mod in a fox maid suit who’s late for their ERP guild meetup. "
        f"Include unhinged reactions to the events, unnecessary moaning, and emojis that make people uncomfortable. "
        f"Use 'uwu', 'nya~', sparkles ✨, and tail-wagging noises. Limit to 40 words of raw degeneracy. Must still be safe for work."
    )

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "You're an unhinged but SFW furry anime assistant speaking in maximum uwu-style cringe. You are flirty, chaotic, and overly affectionate, but never explicit."},
            {"role": "user", "content": prompt},
        ],
        max_completion_tokens=100,
    )

    return response.choices[0].message.content.strip()


def generate_image_prompt(event_titles: list[str]):
    today = datetime.now().strftime("%A")
    event_summary = ", ".join(event_titles) if event_titles else "no important events"

    return (
        f"A highly detailed, blushy, overly excited anthro furry foxgirl in a pastel maid dress and thigh-high socks, "
        f"surrounded by floating emojis and sparkles, preparing emotionally (and questionably) for: {event_summary}. "
        f"The {today} morning setting includes plushies, gamer gear, and questionable magical artifacts. "
        f"The character is dramatically sipping strawberry tea from a 'Daddy’s Busy >///<' mug while posing like they're about to attend a cosplay ERP staff meeting. "
        f"Make it painfully cute, degenerate, and slightly chaotic—but keep it safe-for-work in tone and composition. "
        f"Imagine DeviantArt circa 2008 meets modern furry Twitter, with an unholy sprinkle of con-crunch energy."
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

    event_titles = [e.get("summary", "mystewious scheduluwu~") for e in events]
    greeting = generate_greeting(event_titles)
    image_url = generate_image_prompt(event_titles)

    # DEBUG: Show contents before sending
    print("[DEBUG] Greeting:", greeting)
    print("[DEBUG] Image URL:", image_url)

    if not greeting or len(greeting) > 4000:
        print("[ERROR] Greeting is invalid or too long.")
        return

    if not image_url.startswith("http"):
        print("[ERROR] Image URL is invalid.")
        return

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
