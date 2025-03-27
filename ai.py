# ai.py

import os
import json
import math
import time
import requests
import openai
from datetime import datetime

# -----------------------
# SETUP
# -----------------------
openai.api_key = os.environ.get("OPENAI_API_KEY")

EMBEDDING_MODEL = "text-embedding-ada-002"
EMBEDS_FILE = "/data/embeds.json"

# -----------------------
# HELPER FUNCTIONS
# -----------------------
def embed_text(text: str) -> list[float]:
    """
    Calls OpenAI's Embedding API for text-embedding-ada-002, returning a vector of floats.
    """
    response = openai.Embedding.create(
        model=EMBEDDING_MODEL,
        input=text
    )
    return response["data"][0]["embedding"]

def cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    """
    Simple cosine similarity: dot(a, b) / (||a|| * ||b||).
    """
    dot_prod = sum(a * b for a, b in zip(vec_a, vec_b))
    mag_a = math.sqrt(sum(a * a for a in vec_a))
    mag_b = math.sqrt(sum(b * b for b in vec_b))
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot_prod / (mag_a * mag_b)

# -----------------------
# IN-MEMORY EMBEDDING STORE
# -----------------------
class EventEmbeddingStore:
    """
    Holds event embeddings in memory, loads/saves them to /data/embeds.json for persistence.
    Each item is a dict:
      {
        "event_id": str,
        "event_text": str,
        "embedding": list[float]
      }
    """
    def __init__(self):
        self.data = []
        self.load()

    def load(self):
        """
        Load embeddings from /data/embeds.json if it exists, otherwise start empty.
        """
        if os.path.exists(EMBEDS_FILE):
            try:
                with open(EMBEDS_FILE, "r", encoding="utf-8") as f:
                    stored = json.load(f)
                    if isinstance(stored, list):
                        self.data = stored
                        print(f"[INFO] Loaded {len(self.data)} embeddings from {EMBEDS_FILE}")
                    else:
                        print(f"[WARN] {EMBEDS_FILE} did not contain a list. Ignoring.")
            except Exception as e:
                print(f"[WARN] Failed to load {EMBEDS_FILE}: {e}")
        else:
            print("[INFO] No existing embeddings found; starting empty.")

    def save(self):
        """
        Save current embeddings to /data/embeds.json.
        """
        os.makedirs(os.path.dirname(EMBEDS_FILE), exist_ok=True)
        try:
            with open(EMBEDS_FILE, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[ERROR] Failed to write {EMBEDS_FILE}: {e}")

    def get_all_event_ids(self) -> set:
        """
        Return a set of all event_ids currently stored.
        """
        return {row["event_id"] for row in self.data}

    def add_or_update_event(self, event_id: str, event_text: str):
        """
        If event_id already exists, re-embed with new text. Otherwise insert a new record.
        Then save to disk.
        """
        existing_ids = self.get_all_event_ids()
        if event_id in existing_ids:
            # update existing
            for row in self.data:
                if row["event_id"] == event_id:
                    row["event_text"] = event_text
                    row["embedding"] = embed_text(event_text)
                    print(f"[INFO] Updated embedding for event ID: {event_id}")
                    break
        else:
            # insert new
            row = {
                "event_id": event_id,
                "event_text": event_text,
                "embedding": embed_text(event_text)
            }
            self.data.append(row)
            print(f"[INFO] Added new event embedding: {event_id}")

        self.save()

    def remove_event(self, event_id: str):
        """
        Remove the event from the store (if present) and save.
        """
        before_count = len(self.data)
        self.data = [row for row in self.data if row["event_id"] != event_id]
        after_count = len(self.data)
        if after_count < before_count:
            print(f"[INFO] Removed event embedding: {event_id}")
            self.save()
        else:
            print(f"[WARN] No event found to remove for ID: {event_id}")

    def query(self, query_str: str, top_k: int = 5) -> list[str]:
        """
        Embeds the query, calculates similarity vs. each stored event embedding,
        and returns the top_k event_text strings (sorted by descending similarity).
        """
        if not self.data:
            return []

        query_vector = embed_text(query_str)
        scored = []
        for row in self.data:
            sim = cosine_similarity(query_vector, row["embedding"])
            scored.append((sim, row["event_text"], row["event_id"]))

        # sort by similarity descending
        scored.sort(key=lambda x: x[0], reverse=True)

        # Return just the event_text (plus maybe similarity info)
        results = []
        for i, (sim, text, eid) in enumerate(scored[:top_k], 1):
            results.append(f"(score={sim:.3f}) {text}")
        return results

# A global store you can reuse across your application
store = EventEmbeddingStore()


# -----------------------
# GPT Query with Vector Search
# -----------------------
def ask_ai_any_question(user_query: str, top_k: int = 5) -> str:
    """
    1) Use the store to find top_k relevant events.  
    2) Pass them as context to GPT-4.  
    3) Return GPT's answer.
    
    If you have thousands of events, this ensures you only feed the most relevant ones to GPT.
    """
    # 1) Retrieve top-k similar events
    top_events = store.query(user_query, top_k=top_k)
    if not top_events:
        # If no events are embedded yet, we just do a normal GPT call with no context
        system_msg = (
            "You are a helpful assistant. You have no calendar context available yet."
        )
    else:
        # Combine them into a single text chunk
        relevant_text = "\n\n".join(top_events)
        system_msg = (
            "You are a helpful scheduling assistant with knowledge of the following relevant events:\n\n"
            f"{relevant_text}\n\n"
            "Use them to answer the user's query accurately. "
            "If the query does not relate to these events, answer to the best of your ability."
        )

    # 2) Send to GPT
    try:
        response = openai.ChatCompletion.create(
            model="gpt-4",
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

# -----------------------
# UWU GREETING + IMAGE
# -----------------------
def generate_greeting(event_titles: list[str]) -> str:
    """
    Builds an 'uwu catgirl' greeting referencing the given event_titles.
    """
    today = datetime.now().strftime("%A, %B %d")
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
            model="gpt-4",
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
            max_tokens=200,
            temperature=1.0,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        return f"[Error generating greeting] {e}"

def generate_image_prompt(event_titles: list[str]) -> str:
    """
    Creates a catgirl-themed image prompt referencing event_titles.
    """
    today = datetime.now().strftime("%A")
    event_summary = ", ".join(event_titles) if event_titles else "no important events"

    prompt = (
        f"A highly detailed, blushy, overly excited anime-like catgirl in a pastel maid dress and thigh-high socks, "
        f"surrounded by floating emojis and sparkles, preparing for: {event_summary}. "
        f"The {today} morning setting includes plushies, gamer gear, and questionable magical artifacts. "
        f"The character is dramatically sipping a latte from a 'UwU Boss Mode' mug while posing like they're about to attend a cosplay meetup. "
        f"Painfully cute, slightly chaotic, but strictly safe for work in composition. "
        f"Think DeviantArt circa 2008 meets modern weeb Twitter vibes."
    )
    return prompt

def generate_image(prompt: str, max_retries: int = 3) -> str:
    """
    Calls OpenAI Image API (DALL·E-like) to generate an image. 
    Downloads it locally and returns the file path.
    Retries up to max_retries on transient errors.
    """
    for attempt in range(max_retries):
        try:
            response = openai.Image.create(
                prompt=prompt,
                n=1,
                size="1024x1024",
                response_format="url"
            )
            image_url = response["data"][0]["url"]

            # Download
            img_data = requests.get(image_url)
            img_data.raise_for_status()

            # Save locally
            os.makedirs("generated_images", exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"generated_images/generated_{ts}.png"
            with open(filename, "wb") as f:
                f.write(img_data.content)

            return filename

        except openai.error.OpenAIError as e:
            print(f"[OpenAI Policy/Error] {e}")
            if attempt + 1 < max_retries:
                time.sleep(1)
                continue
            else:
                raise
        except Exception as e:
            print(f"[ERROR] Unexpected error generating image: {e}")
            if attempt + 1 < max_retries:
                time.sleep(1)
                continue
            else:
                raise

    raise RuntimeError("Image generation failed after multiple retries.")

# -----------------------
# Example usage (if run directly)
# -----------------------
if __name__ == "__main__":
    # Quick demonstration of the vector-based approach:

    # 1) Suppose you have some events to embed:
    # In a real system, you'd fetch from your calendars, then for each:
    example_events = [
        {
            "id": "event1",
            "summary": "Board Meeting",
            "start": {"dateTime": "2025-04-01T10:00:00Z"},
            "end": {"dateTime": "2025-04-01T11:00:00Z"},
            "description": "Discuss financial statements."
        },
        {
            "id": "event2",
            "summary": "Coffee with Sarah",
            "start": {"dateTime": "2025-04-02T09:30:00Z"},
            "end": {"dateTime": "2025-04-02T10:00:00Z"},
            "description": "Catching up with an old friend."
        }
    ]

    # 2) Convert them to text and embed them in the store
    for e in example_events:
        eid = e["id"]
        title = e.get("summary", "")
        start = e["start"].get("dateTime") or e["start"].get("date", "")
        end = e["end"].get("dateTime") or e["end"].get("date", "")
        desc = e.get("description", "")
        text_repr = f"Title: {title}\nStart: {start}\nEnd: {end}\nDesc: {desc}"
        store.add_or_update_event(eid, text_repr)

    # 3) Ask a question referencing these events
    user_query = "When is the financial meeting?"
    answer = ask_ai_any_question(user_query, top_k=2)
    print("\nUser query:", user_query)
    print("Answer:\n", answer)

    # 4) For the catgirl greeting:
    greeting = generate_greeting(["Board Meeting", "Coffee with Sarah"])
    print("\nGreeting:\n", greeting)

    # 5) Generate an image:
    prompt = generate_image_prompt(["Board Meeting", "Coffee with Sarah"])
    image_path = generate_image(prompt)
    print("\nGenerated image at:", image_path)
