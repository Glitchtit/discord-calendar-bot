# embeddings.py

import os
import openai
import math
import json
import time
import requests

openai.api_key = os.environ["OPENAI_API_KEY"]

EMBEDDING_MODEL = "text-embedding-ada-002"
EMBEDS_FILE = os.environ.get("EMBEDS_FILE", "/data/embeds.json")


def embed_text(text: str) -> list[float]:
    """
    Calls OpenAI to get a vector embedding for the given text using the chosen model.
    Returns a list of floats.
    """
    response = openai.Embedding.create(
        model=EMBEDDING_MODEL,
        input=text
    )
    return response["data"][0]["embedding"]


def cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    """
    Computes the cosine similarity: dot(a, b) / (||a|| * ||b||).
    """
    dot_prod = sum(a * b for a, b in zip(vec_a, vec_b))
    mag_a = math.sqrt(sum(a * a for a in vec_a))
    mag_b = math.sqrt(sum(b * b for b in vec_b))
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot_prod / (mag_a * mag_b)


class EventEmbeddingStore:
    """
    Manages event embeddings in memory, with the ability to load from /data/embeds.json
    and save back to it.
    Each item in self.data is a dict:
      {
        "event_id": str,
        "event_text": str,
        "embedding": [floats]
      }
    """

    def __init__(self):
        # Load existing embeddings from file (if any)
        self.data = []
        self.load()

    def load(self):
        """
        Loads embeddings from EMBEDS_FILE (/data/embeds.json).
        If the file doesn't exist or is invalid, we start with an empty list.
        """
        if os.path.exists(EMBEDS_FILE):
            try:
                with open(EMBEDS_FILE, "r", encoding="utf-8") as f:
                    stored = json.load(f)
                    # Expecting a list of dict items { "event_id", "event_text", "embedding" }
                    if isinstance(stored, list):
                        self.data = stored
                    else:
                        print("[WARN] /data/embeds.json did not contain a list; ignoring.")
            except Exception as e:
                print(f"[WARN] Failed to load /data/embeds.json: {e}")
        else:
            print("[INFO] /data/embeds.json not found; starting empty.")

    def save(self):
        """
        Writes current self.data to EMBEDS_FILE (/data/embeds.json).
        """
        os.makedirs(os.path.dirname(EMBEDS_FILE), exist_ok=True)
        try:
            with open(EMBEDS_FILE, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[ERROR] Failed to write {EMBEDS_FILE}: {e}")

    def get_all_event_ids(self) -> set:
        return {item["event_id"] for item in self.data}

    def add_or_update_event(self, event_id: str, event_text: str):
        """
        If 'event_id' is already in the store, update its text + embedding.
        Otherwise, embed it and add a new entry.
        After changes, automatically save.
        """
        existing_ids = self.get_all_event_ids()
        if event_id in existing_ids:
            # Update existing
            for row in self.data:
                if row["event_id"] == event_id:
                    row["event_text"] = event_text
                    row["embedding"] = embed_text(event_text)
                    break
            print(f"[INFO] Updated embedding for event: {event_id}")
        else:
            # Insert new
            emb = embed_text(event_text)
            self.data.append({
                "event_id": event_id,
                "event_text": event_text,
                "embedding": emb
            })
            print(f"[INFO] Added new event embedding: {event_id}")
        self.save()

    def remove_event(self, event_id: str):
        """
        Removes an event’s embedding from the store, then saves.
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
        Embeds the user query, then computes cosine similarity to each event in store.
        Returns a list of the top_k event_text strings by similarity.
        """
        if not self.data:
            return []

        query_emb = embed_text(query_str)
        scored = []
        for row in self.data:
            sim = cosine_similarity(query_emb, row["embedding"])
            scored.append((sim, row["event_text"], row["event_id"]))

        # Sort descending by similarity
        scored.sort(key=lambda x: x[0], reverse=True)
        # Return only the event_text portion for top_k
        return [f"(Similarity={round(s,3)}) {txt}" for (s, txt, eid) in scored[:top_k]]


# Example usage
if __name__ == "__main__":
    store = EventEmbeddingStore()

    # Suppose these are the events you loaded from your calendar:
    events = [
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
            "description": "Meeting a friend to catch up."
        }
    ]

    # Construct text and add them to the store
    for e in events:
        event_id = e["id"]
        summary = e["summary"]
        start = e["start"].get("dateTime") or e["start"].get("date", "")
        end = e["end"].get("dateTime") or e["end"].get("date", "")
        desc = e.get("description", "")

        # Build a textual representation to embed
        event_text = (
            f"Title: {summary}\n"
            f"Start: {start}\n"
            f"End: {end}\n"
            f"Description: {desc}"
        )

        # Add or update in the store
        store.add_or_update_event(event_id, event_text)

    # Now let's do a query
    user_query = "When is that financial meeting?"
    top_matches = store.query(user_query, top_k=2)

    print("\nQuery:", user_query)
    for i, match in enumerate(top_matches, 1):
        print(f"{i}. {match}")
