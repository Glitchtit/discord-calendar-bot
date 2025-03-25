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
SUNO_BASE_URL = "https://sunoapi.org/api"

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

def generate_image(prompt: str) -> str:
    response = client.images.generate(
        model="dall-e-3",
        prompt=prompt,
        size="1024x1024",
        quality="standard",
        n=1
    )
    return response.data[0].url

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

def generate_music_clip_suno(lyrics: str, title: str) -> str:
    if not SUNO_API_KEY:
        print("[ERROR] No SUNO_API_KEY provided.")
        return ""

    headers = {
        "Authorization": f"Bearer {SUNO_API_KEY}",
        "Content-Type": "application/json",
    }

    gen_payload = {
        "title": title,
        "tags": ["funny", "cringe", "ai-generated"],
        "prompt": lyrics
    }

    try:
        gen_response = requests.post(f"{SUNO_BASE_URL}/generate", headers=headers, json=gen_payload)
        gen_response.raise_for_status()
        uuid = gen_response.json().get("uuid")
        if not uuid:
            print("[ERROR] UUID not returned from Suno.")
            return ""
    except Exception as e:
        print(f"[ERROR] Suno generate request failed: {e}")
        return ""

    for attempt in range(30):
        time.sleep(1)
        try:
            status_response = requests.get(f"{SUNO_BASE_URL}/status/{uuid}", headers=headers)
            status_response.raise_for_status()
            data = status_response.json()
            audio_url = data.get("audio_url")
            if audio_url:
                return audio_url
        except Exception as e:
            print(f"[DEBUG] Polling error: {e}")

    print("[ERROR] Timed out waiting for Suno song.")
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
