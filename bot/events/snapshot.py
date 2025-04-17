"""
snapshot.py: Event snapshot persistence and tracking.
"""
from utils.logging import logger
import os
import json

def load_previous_events(server_id: int):
    try:
        from .calendar_loading import get_events_file
        path = get_events_file(server_id)
        if (os.path.exists(path)):
            with open(path, "r", encoding="utf-8") as f:
                logger.debug(f"Loaded previous event snapshot from disk at {path}")
                return json.load(f)
    except json.JSONDecodeError:
        logger.warning(f"Previous events file at {path} corrupted. Starting fresh.")
    except Exception as e:
        logger.exception(f"Error loading previous events from {path}: {e}")
    return {}

def save_current_events_for_key(server_id: int, key, events):
    try:
        from .calendar_loading import get_events_file
        logger.debug(f"Saving {len(events)} events under key: {key}")
        all_data = load_previous_events(server_id)
        all_data[key] = events
        events_file_path = get_events_file(server_id)
        with open(events_file_path, "w", encoding="utf-8") as f:
            import json
            json.dump(all_data, f, ensure_ascii=False, indent=4)
        logger.info(f"Saved events for key '{key}' to {events_file_path}.")
    except Exception as e:
        logger.exception(f"Error saving events for key {key}: {e}")

def load_post_tracking(server_id: int) -> dict:
    try:
        from .calendar_loading import get_events_file
        path = get_events_file(server_id)
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("daily_posts", {})
    except json.JSONDecodeError:
        logger.warning(f"Tracking file for server {server_id} is corrupted. Starting fresh.")
    except Exception as e:
        logger.exception(f"Error loading post tracking for server {server_id}: {e}")
    return {}
