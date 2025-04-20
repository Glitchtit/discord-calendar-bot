# ╔════════════════════════════════════════════════════════════════════════════╗
# ║                  BOT EVENTS CALENDAR LOADING MODULE                    ║
# ║    Handles loading calendar configurations from server files and         ║
# ║    grouping them by user/tag.                                            ║
# ╚════════════════════════════════════════════════════════════════════════════╝

"""
calendar_loading.py: Calendar loading and grouping logic.
"""
import os
import json
from utils.logging import logger
from config.server_config import load_server_config, get_all_server_ids, save_server_config, register_calendar_reload_callback

# ╔════════════════════════════════════════════════════════════════════════════╗
# ║ GLOBAL VARIABLES                                                          ║
# ╚════════════════════════════════════════════════════════════════════════════╝

GROUPED_CALENDARS = {} # Stores loaded calendars, keyed by user_id/tag
TAG_NAMES = {}         # Maps user_id/tag to a display name
TAG_COLORS = {}        # Maps user_id/tag to a display color (hex integer)

# ╔════════════════════════════════════════════════════════════════════════════╗
# ║ TAG UTILITIES                                                             ║
# ╚════════════════════════════════════════════════════════════════════════════╝

# --- get_name_for_tag ---
# Retrieves the display name for a given user ID or tag.
# Falls back to the tag itself if no specific name is found.
# Args:
#     tag: The user ID or tag string.
# Returns: The display name string.
def get_name_for_tag(tag: str) -> str:
    if not tag:
        return "Unknown"
    return TAG_NAMES.get(tag, tag)

# --- get_color_for_tag ---
# Retrieves the display color (as a hex integer) for a given user ID or tag.
# Falls back to a default grey color (0x95a5a6) if no specific color is found.
# Args:
#     tag: The user ID or tag string.
# Returns: The color as a hex integer.
def get_color_for_tag(tag: str) -> int:
    if not tag:
        return 0x95a5a6
    return TAG_COLORS.get(tag, 0x95a5a6)

# ╔════════════════════════════════════════════════════════════════════════════╗
# ║ FILE PATH UTILITY                                                         ║
# ╚════════════════════════════════════════════════════════════════════════════╝

# --- get_events_file ---
# Constructs the absolute path for the event snapshot JSON file for a specific server.
# Ensures the necessary directory structure exists within the /data volume.
# Args:
#     server_id: The ID of the Discord server.
# Returns: The absolute path string to the events.json file.
def get_events_file(server_id: int) -> str:
    """Return the path to the event snapshot file for a server."""
    # Use a consistent path for event snapshots (events.json) per server
    # Use absolute path /data as the base, assuming it's the mounted volume root
    base_dir = os.path.join("/data", "servers", str(server_id))
    os.makedirs(base_dir, exist_ok=True)
    return os.path.join(base_dir, "events.json")

# ╔════════════════════════════════════════════════════════════════════════════╗
# ║ CALENDAR LOADING LOGIC                                                    ║
# ╚════════════════════════════════════════════════════════════════════════════╝

# --- load_calendars_from_server_configs ---
# Clears and repopulates the global `GROUPED_CALENDARS` dictionary.
# Iterates through all known server IDs, loads their `config.json`.
# Parses the 'calendars' list from each config.
# Groups calendars by their 'user_id' (tag), ensuring user_id is a string.
# Defaults missing user_ids to "1" (server-wide/everyone) and saves the config change.
# Appends shared calendars (user_id "1") to all other users' calendar lists.
# Registers itself as a callback for automatic reloading when configs change.
# Returns: The populated `GROUPED_CALENDARS` dictionary.
def load_calendars_from_server_configs():
    global GROUPED_CALENDARS
    GROUPED_CALENDARS.clear()
    missing_user_id_count = 0
    server_ids = get_all_server_ids()
    logger.info(f"Found {len(server_ids)} server IDs to load calendars from: {server_ids}")
    if not server_ids:
        docker_dir = "/data/servers"
        if os.path.exists(docker_dir):
            try:
                docker_ids = []
                for entry in os.listdir(docker_dir):
                    if entry.isdigit():
                        docker_path = os.path.join(docker_dir, entry, "config.json")
                        if os.path.exists(docker_path):
                            docker_ids.append(int(entry))
                if docker_ids:
                    server_ids = docker_ids
            except Exception as e:
                logger.error(f"Error checking Docker directory: {e}")
    for server_id in server_ids:
        # SIMPLIFIED: Directly load using the function that handles path checking
        config = load_server_config(server_id)
        if not config: # Skip if config loading failed or returned empty
            logger.warning(f"Could not load or found empty config for server {server_id}. Skipping.")
            continue

        calendars = config.get("calendars", [])
        for calendar in calendars:
            # Ensure user_id is stored as string
            raw_user_id = calendar.get("user_id")
            if raw_user_id is None:
                missing_user_id_count += 1
                logger.warning(f"Calendar '{calendar.get('name', 'Unnamed Calendar')}' in server {server_id} is missing user_id. Defaulting to '1' (everyone).")
                raw_user_id = "1"
                calendar["user_id"] = str(raw_user_id)
                save_server_config(server_id, config)
            user_id = str(raw_user_id)
            calendar["user_id"] = user_id
            if user_id not in GROUPED_CALENDARS:
                GROUPED_CALENDARS[user_id] = []
            GROUPED_CALENDARS[user_id].append({
                "server_id": server_id,
                "type": calendar["type"],
                "id": calendar["id"],
                "name": calendar.get("name", "Unnamed Calendar"),
                "user_id": user_id
            })
    # --- NEW: Add shared (everyone) calendars to all users except '1' ---
    shared = GROUPED_CALENDARS.get("1", [])
    if shared:
        for user_id in list(GROUPED_CALENDARS.keys()):
            if user_id != "1":
                GROUPED_CALENDARS[user_id].extend(shared)
    register_calendar_reload_callback(load_calendars_from_server_configs)
    return GROUPED_CALENDARS
