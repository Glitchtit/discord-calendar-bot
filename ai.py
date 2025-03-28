import os
import json
import time
import requests
import openai
from datetime import datetime
from dateutil import tz
from embeddings import embed_text, cosine_similarity, EventEmbeddingStore

store = EventEmbeddingStore()

def ask_ai_any_question(user_query: str, top_k: int = 5) -> str:
    now_dt = datetime.now(tz=tz.tzlocal())
    now_str = now_dt.strftime("%A, %B %d, %Y")
    q = user_query.lower().strip()

    # 1️⃣ Literal day-of-date fallback
    if q in {
        "what is today", "what's today", "what day is today",
        "what's the date", "today's date", "what day is it", "what date is it"
    }:
        return f"Today is {now_str}!"

    # 2️⃣ Natural-language date range handling (e.g., "tomorrow", "next week")
    date_range = extract_date_range_from_query(user_query)
    if date_range:
        start, end = date_range
        all_events = load_previous_events().get(ALL_EVENTS_KEY, [])
        matched = []
        for e in all_events:
            start_str = e["start"].get("dateTime", e["start"].get("date"))
            try:
                dt = datetime.fromisoformat(start_str.replace("Z", "+00:00")).astimezone(tz=tz.tzlocal())
                if start <= dt <= end:
                    matched.append(f"- {e.get('summary')} ({dt.strftime('%A, %B %d %H:%M')})")
            except Exception:
                continue

        if matched:
            return (
                f"📅 Events from {start.strftime('%A %B %d')} to {end.strftime('%A %B %d')}:\n\n"
                + "\n".join(matched)
            )
        else:
            return f"📭 No events found between {start.strftime('%A %B %d')} and {end.strftime('%A %B %d')}."

    # 3️⃣ Semantic fallback
    top_events = store.query(user_query, top_k=top_k)
    if not top_events:
        system_msg = (
            f"You are a helpful assistant. Today is {now_str}. "
            "You have no calendar context available yet."
        )
    else:
        relevant_text = "\n\n".join(top_events)
        system_msg = (
            f"You are a helpful scheduling assistant. Today is {now_str}.\n\n"
            "You have knowledge of the following relevant events:\n\n"
            f"{relevant_text}\n\n"
            "Use them to answer the user's query accurately. "
            "If the query does not relate to these events, answer to the best of your ability."
        )

    try:
        import openai
        response = openai.ChatCompletion.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_query},
            ],
            max_tokens=900,
            temperature=0.7,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        return f"[ERROR calling OpenAI] {e}"

def generate_greeting(event_titles: list[str]) -> str:
    today = datetime.now(tz=tz.tzlocal()).strftime("%A, %B %d")
    event_summary = ", ".join(event_titles) if event_titles else "no special events"
    prompt = (
        f"H-hewwo~! It's {today}, and we've got some *extra thicc* scheduluwus coming up: {event_summary}~ (⁄ ⁄>⁄ ▽ ⁄<⁄ ⁄)💦 "
        f"Write a shamelessly flirty, deranged anime-catgirl hybrid greeting, dripping with unfiltered 'owo what's this' energy. "
        f"It should sound like it was written by a Discord mod in a maid suit who’s late for their world of warcraft guild meetup. "
        f"Include unhinged reactions to the events, questionable sound effects, and emojis that make people uncomfortable. "
        f"Use 'uwu', 'nya~', sparkles ✨, and tail-wagging noises. Limit to ~80 words. Must still be safe for work."
    )
    try:
        response = openai.ChatCompletion.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are an unhinged but SFW japanese anime-catgirl assistant speaking in maximum uwu-style cringe. "
                        "You are flirty, chaotic, and overly affectionate, but never explicit. "
                        "Your replies remain safe for work."
                    )
                },
                {"role": "user", "content": prompt},
            ],
            max_tokens=900,
            temperature=1.0,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        return f"[Error generating greeting] {e}"

def generate_image_prompt(event_titles: list[str]) -> str:
    today = datetime.now(tz=tz.tzlocal()).strftime("%A")
    short_titles = []
    total_len = 0
    for title in event_titles:
        if total_len + len(title) > 500 or len(short_titles) >= 10:
            break
        short_titles.append(title)
        total_len += len(title)
    summary = ", ".join(short_titles) or "no important events"
    prompt = (
        f"A highly detailed, blushy, overly excited anime-like catgirl in a pastel maid dress and thigh-high socks, "
        f"surrounded by floating emojis and sparkles, preparing for: {summary}. "
        f"The {today} morning setting includes plushies, gamer gear, and questionable magical artifacts. "
        f"The character is dramatically sipping a latte from a 'UwU Boss Mode' mug while posing like they're about to attend a cosplay meetup. "
        f"Painfully cute, slightly chaotic, but strictly safe for work in composition. "
        f"Think DeviantArt circa 2008 meets modern weeb Twitter vibes."
    )
    try:
        from log import log
        log.debug(f"[Image Prompt] Length: {len(prompt)} chars")
    except:
        pass
    return prompt

def generate_image(prompt: str, max_retries: int = 3) -> str:
    for attempt in range(max_retries):
        try:
            response = openai.Image.create(
                model="dall-e-3",
                prompt=prompt,
                n=1,
                size="1024x1024",
                quality="hd",
                response_format="url"
            )
            image_url = response["data"][0]["url"]
            img_data = requests.get(image_url)
            img_data.raise_for_status()
            os.makedirs("/data/art", exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"/data/art/generated_{ts}.png"
            with open(filename, "wb") as f:
                f.write(img_data.content)
            return filename
        except openai.error.OpenAIError as e:
            print(f"[OpenAI Error] {e}")
            if attempt + 1 < max_retries:
                time.sleep(2)
                continue
            else:
                raise
        except Exception as e:
            print(f"[ERROR] Unexpected error generating image: {e}")
            if attempt + 1 < max_retries:
                time.sleep(2)
                continue
            else:
                raise
    raise RuntimeError("Image generation failed after multiple retries.")
