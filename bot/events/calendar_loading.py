"""
calendar_loading.py: Calendar loading and grouping logic.
"""
import os
import json
from utils.logging import logger
from config.server_config import load_server_config, get_all_server_ids, save_server_config, register_calendar_reload_callback

GROUPED_CALENDARS = {}
TAG_NAMES = {}
TAG_COLORS = {}

def get_name_for_tag(tag: str) -> str:
    if not tag:
        return "Unknown"
    return TAG_NAMES.get(tag, tag)

def get_color_for_tag(tag: str) -> int:
    if not tag:
        return 0x95a5a6
    return TAG_COLORS.get(tag, 0x95a5a6)

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
        docker_path = f"/data/servers/{server_id}/config.json"
        config = None
        if os.path.exists(docker_path):
            try:
                with open(docker_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
            except Exception as e:
                logger.warning(f"Error loading from Docker path: {e}")
        if config is None:
            config = load_server_config(server_id)
        calendars = config.get("calendars", [])
        for calendar in calendars:
            # Ensure user_id is stored as string
            raw_user_id = calendar.get("user_id")
            if raw_user_id is None:
                missing_user_id_count += 1
                raw_user_id = server_id
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
    register_calendar_reload_callback(load_calendars_from_server_configs)
    return GROUPED_CALENDARS
