import os
import openai
import math
import json
from log import log

openai.api_key = os.environ["OPENAI_API_KEY"]

EMBEDDING_MODEL = "text-embedding-ada-002"
EMBEDS_FILE = "/data/embeds.json"

def embed_text(text: str) -> list[float]:
    response = openai.Embedding.create(
        model=EMBEDDING_MODEL,
        input=text
    )
    return response["data"][0]["embedding"]

def cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    dot_prod = sum(a * b for a, b in zip(vec_a, vec_b))
    mag_a = math.sqrt(sum(a * a for a in vec_a))
    mag_b = math.sqrt(sum(b * b for b in vec_b))
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot_prod / (mag_a * mag_b)

class EventEmbeddingStore:
    def __init__(self):
        self.data = []
        self.load()

    def load(self):
        if os.path.exists(EMBEDS_FILE):
            try:
                with open(EMBEDS_FILE, "r", encoding="utf-8") as f:
                    stored = json.load(f)
                    if isinstance(stored, list):
                        self.data = stored
                    else:
                        log.warning("[Embeds] EMBEDS_FILE is not a list.")
            except Exception as e:
                log.warning(f"[Embeds] Failed to load {EMBEDS_FILE}: {e}")
        else:
            log.info("[Embeds] No existing embeddings found.")

    def save(self):
        os.makedirs(os.path.dirname(EMBEDS_FILE), exist_ok=True)
        try:
            with open(EMBEDS_FILE, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            log.error(f"[Embeds] Failed to write {EMBEDS_FILE}: {e}")

    def get_all_event_ids(self) -> set:
        return {item["event_id"] for item in self.data}

    def add_or_update_event(self, event_id: str, event_text: str):
        existing_ids = self.get_all_event_ids()
        if event_id in existing_ids:
            for row in self.data:
                if row["event_id"] == event_id:
                    row["event_text"] = event_text
                    row["embedding"] = embed_text(event_text)
                    break
        else:
            self.data.append({
                "event_id": event_id,
                "event_text": event_text,
                "embedding": embed_text(event_text)
            })
        self.save()

    def remove_event(self, event_id: str):
        before_count = len(self.data)
        self.data = [row for row in self.data if row["event_id"] != event_id]
        after_count = len(self.data)
        if after_count < before_count:
            self.save()

    def query(self, query_str: str, top_k: int = 5) -> list[str]:
        if not self.data:
            return []

        query_emb = embed_text(query_str)
        scored = []
        for row in self.data:
            sim = cosine_similarity(query_emb, row["embedding"])
            scored.append((sim, row["event_text"], row["event_id"]))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [f"(score={sim:.3f}) {text}" for sim, text, _ in scored[:top_k]]
