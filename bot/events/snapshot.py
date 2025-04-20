# ╔════════════════════════════════════════════════════════════════════════════╗
# ║                    BOT EVENTS SNAPSHOT MODULE                        ║
# ║    Handles loading and saving event snapshots and post tracking data     ║
# ║    to disk for persistence.                                              ║
# ╚════════════════════════════════════════════════════════════════════════════╝

"""
snapshot.py: Event snapshot persistence and tracking.
"""

from utils.logging import logger
import os
import json

# ╔════════════════════════════════════════════════════════════════════════════╗
# ║ EVENT SNAPSHOT MANAGEMENT                                                 ║
# ╚════════════════════════════════════════════════════════════════════════════╝

# --- load_previous_events ---
# Loads the entire event snapshot JSON file for a given server ID.
# The snapshot file stores events grouped by keys (e.g., 'daily', 'weekly').
# Handles file not found, JSON decoding errors, and other exceptions.
# Args:
#     server_id: The ID of the Discord server.
# Returns: A dictionary representing the loaded snapshot data, or an empty dictionary on error/file not found.
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

# --- save_current_events_for_key ---
# Saves a list of events under a specific key within the server's event snapshot file.
# It reads the existing snapshot, updates the data for the given key, and writes the entire snapshot back to the file.
# Args:
#     server_id: The ID of the Discord server.
#     key: The string key under which to save the events (e.g., 'daily', 'weekly').
#     events: The list of event dictionaries to save.
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

# ╔════════════════════════════════════════════════════════════════════════════╗
# ║ POST TRACKING MANAGEMENT                                                  ║
# ╚════════════════════════════════════════════════════════════════════════════╝

# --- load_post_tracking ---
# Loads the 'daily_posts' tracking data from the server's event snapshot file.
# This data is used to keep track of which daily events have already been posted to avoid duplicates.
# Handles file not found, JSON decoding errors, and other exceptions.
# Args:
#     server_id: The ID of the Discord server.
# Returns: A dictionary representing the daily post tracking data, or an empty dictionary on error/file not found.
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
