import os
import json
from typing import Dict, List, Any
from src.core.logger import logger

# ╔════════════════════════════════════════════════════════════════════╗
# ║ 💾 Event Snapshot Persistence                                      ║
# ║ Handles loading and saving event data for change detection        ║
# ╚════════════════════════════════════════════════════════════════════╝

EVENTS_FILE = "/data/events.json"

# Fallback directory for events if primary location is unavailable
FALLBACK_EVENTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../data")

def load_previous_events() -> Dict[str, List[Any]]:
    """Load previously stored events from disk."""
    try:
        if os.path.exists(EVENTS_FILE):
            with open(EVENTS_FILE, "r", encoding="utf-8") as f:
                logger.debug("Loaded previous event snapshot from disk.")
                return json.load(f)
    except json.JSONDecodeError:
        logger.warning("Previous events file corrupted. Starting fresh.")
    except Exception as e:
        logger.exception(f"Error loading previous events: {e}")
    return {}

def save_current_events_for_key(key: str, events: List[Any]) -> None:
    """Save events for a specific key to disk."""
    try:
        logger.debug(f"Saving {len(events)} events under key: {key}")
        all_data = load_previous_events()
        all_data[key] = events
        
        # Ensure directory exists
        os.makedirs(os.path.dirname(EVENTS_FILE), exist_ok=True)
        
        with open(EVENTS_FILE, "w", encoding="utf-8") as f:
            json.dump(all_data, f, ensure_ascii=False)
        logger.info(f"Saved events for key '{key}'.")
    except Exception as e:
        logger.exception(f"Error saving events for key {key}: {e}")

def clear_event_storage() -> None:
    """Clear all stored event data."""
    try:
        if os.path.exists(EVENTS_FILE):
            os.remove(EVENTS_FILE)
            logger.info("Event storage cleared.")
    except Exception as e:
        logger.exception(f"Error clearing event storage: {e}")