"""
fingerprint.py: Event fingerprinting utilities.
"""
from utils.logging import logger
import hashlib
import json
from datetime import datetime

def compute_event_fingerprint(event: dict) -> str:
    if not event or not isinstance(event, dict):
        logger.error("Invalid event data for fingerprinting")
        return ""
    try:
        def normalize_time(val: str) -> str:
            if not val:
                return ""
            if "Z" in val:
                val = val.replace("Z", "+00:00")
            if "T" not in val:
                return val
            try:
                dt = datetime.fromisoformat(val)
                return dt.isoformat(timespec="minutes")
            except (ValueError, TypeError):
                logger.warning(f"Could not parse datetime: {val}")
                return val
        def clean(text: str) -> str:
            if not text:
                return ""
            if not isinstance(text, str):
                return str(text)
            return " ".join(text.strip().split())
        summary = clean(event.get("summary", ""))
        location = clean(event.get("location", ""))
        description = clean(event.get("description", ""))
        start_container = event.get("start", {})
        end_container = event.get("end", {})
        if not isinstance(start_container, dict):
            start_container = {"date": str(start_container)}
        if not isinstance(end_container, dict):
            end_container = {"date": str(end_container)}
        start_raw = start_container.get("dateTime", start_container.get("date", ""))
        end_raw = end_container.get("dateTime", end_container.get("date", ""))
        start = normalize_time(start_raw)
        end = normalize_time(end_raw)
        trimmed = {
            "summary": summary,
            "start": start,
            "end": end,
            "location": location,
            "description": description
        }
        normalized_json = json.dumps(trimmed, sort_keys=True)
        return hashlib.md5(normalized_json.encode("utf-8")).hexdigest()
    except Exception as e:
        event_id = event.get("id", "unknown")
        event_summary = event.get("summary", "untitled")
        logger.exception(f"Error computing fingerprint for event '{event_summary}' (ID: {event_id}): {e}")
        fallback_str = f"{event.get('id', '')}|{event.get('summary', '')}"
        return hashlib.md5(fallback_str.encode("utf-8")).hexdigest()
