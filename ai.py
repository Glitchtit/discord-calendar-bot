import os
import time
import random
import requests
from datetime import datetime
from openai import OpenAI
from dateutil import tz

# Load environment variables
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
SUNO_API_KEY = os.environ.get("SUNO_API_KEY")

client = OpenAI(api_key=OPENAI_API_KEY)

GENRES = [
    "hyperpop", "synthwave", "lo-fi", "metalcore", "kawaii future bass",
    "eurobeat", "trap", "pop punk", "vaporwave"
]

def generate_greeting(event_titles: list[str]):
    today = datetime.now().strftime("%A, %B %d")
    event_summary = ", ".join(event_titles) if event_titles else "no special events"

    prompt = (
        f"H-hewwo~! It's {today}, and we've got some *extra thicc* scheduluwus coming up: {event_summary}~ (⁄ ⁄>⁄ ▽ ⁄<⁄ ⁄)💦 "
        f"Write a shamelessly flirty, deranged furry-anime hybrid greeting, dripping with unfiltered 'owo what's this' energy. "
        f"It should sound like it was written by a Discord mod in a fox maid suit who’s late for their ERP guild meetup. "
        f"Include unhinged reactions to the events, questionable sound effects, and emojis that make people uncomfortable. "
        f"Use 'uwu', 'nya~', sparkles ✨, and tail-wagging noises. Limit to 40 words of raw degeneracy. Must still be safe for work."
    )

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "system",
                "content": (
                    "You're an unhinged but SFW furry anime assistant speaking in maximum uwu-style cringe. "
                    "You are flirty, chaotic, and overly affectionate, but never explicit."
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
        f"A highly detailed, blushy, overly excited anthro furry foxgirl in a pastel maid dress and thigh-high socks, "
        f"surrounded by floating emojis and sparkles, preparing emotionally (and questionably) for: {event_summary}. "
        f"The {today} morning setting includes plushies, gamer gear, and questionable magical artifacts. "
        f"The character is dramatically sipping strawberry tea from a 'UwU Boss Mode' mug while posing like they're about to attend a cosplay RP meetup. "
        f"Make it painfully cute, degenerate, and slightly chaotic—but keep it safe-for-work in tone and composition. "
        f"Imagine DeviantArt circa 2008 meets modern furry Twitter, with an unholy sprinkle of con-crunch energy."
    )

def generate_image(prompt: str, max_retries: int = 3) -> str:
    for attempt in range(max_retries):
        try:
            response = client.images.generate(
                model="dall-e-3",
                prompt=prompt,
                size="1024x1024",
                quality="standard",
                n=1
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
                raise  # Re-raise other types of BadRequestError

        except Exception as e:
            print(f"[ERROR] Unexpected error on image generation: {e}")
            if attempt + 1 == max_retries:
                raise

    raise RuntimeError("Image generation failed after retries.")


def generate_song_lyrics(greeting: str) -> tuple[str, str, str]:
    genre = random.choice(GENRES)
    title_prompt = (
        f"Give a ridiculously dramatic song title in the style of {genre} based on this greeting: \"{greeting}\""
    )
    lyrics_prompt = (
        f"Write cringe but catchy lyrics for a 20-second {genre} song, based on this greeting: \"{greeting}\". "
        f"Include at least one 'nya~', one 'uwu', and one over-the-top reaction to a calendar event."
    )

    title_resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": title_prompt}],
        max_tokens=30,
    )

    lyrics_resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": lyrics_prompt}],
        max_tokens=200,
    )

    return title_resp.choices[0].message.content.strip(), lyrics_resp.choices[0].message.content.strip(), genre

BASE_URL = "https://apibox.erweima.ai"

def call_suno_api(endpoint: str, data: dict) -> dict:
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {SUNO_API_KEY}"
    }
    
    response = requests.post(f"{BASE_URL}{endpoint}", headers=headers, json=data)
    result = response.json()

    if result.get("code") != 200:
        raise Exception(f"[SUNO API ERROR] {result.get('msg')}")
    
    return result

def generate_music_clip_suno(lyrics: str, title: str) -> str:
    data = {
        "prompt": lyrics,
        "callBackUrl": "",  # Optional: set if you want async
        "title": title
    }

    try:
        result = call_suno_api("/api/v1/music", data)
        song_info = result.get("data", {})
        audio_url = song_info.get("musicUrl") or song_info.get("audio_url")

        if not audio_url:
            print("[ERROR] No audio URL in Suno response.")
            return ""

        return audio_url

    except Exception as e:
        print(f"[ERROR] Suno music generation failed: {e}")
        return ""


def post_greeting_to_discord(events: list[dict] = []):
    if not DISCORD_WEBHOOK_URL:
        print("[DEBUG] No DISCORD_WEBHOOK_URL set.")
        return

    event_titles = [e.get("summary", "mystewious scheduluwu~") for e in events]
    greeting = generate_greeting(event_titles)
    image_prompt = generate_image_prompt(event_titles)
    image_url = generate_image(image_prompt)
    song_title, song_lyrics, genre = generate_song_lyrics(greeting)
    music_url = generate_music_clip_suno(song_lyrics, song_title)

    print("[DEBUG] Greeting:", greeting)
    print("[DEBUG] Image URL:", image_url)
    print("[DEBUG] Music URL:", music_url)

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

    if music_url:
        payload["embeds"].append(
            {
                "title": f"🎵 Song of the Day: *{song_title}*",
                "description": f"*Genre:* {genre}\n[▶️ Listen on Suno]({music_url})\n\n*Lyrics Preview:*\n{song_lyrics}",
                "color": 0xff69b4
            }
        )

    resp = requests.post(DISCORD_WEBHOOK_URL, json=payload)
    if resp.status_code not in [200, 204]:
        print(f"[DEBUG] Discord greeting post failed: {resp.status_code} {resp.text}")
    else:
        print("[DEBUG] Discord greeting post successful.")

if __name__ == "__main__":
    post_greeting_to_discord()
