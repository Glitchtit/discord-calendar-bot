"""
server_config.py: Server-specific configuration management for the calendar bot.

This module manages server-specific configurations, including calendars and admin settings.
Configurations are stored in JSON files under the /data/servers directory.
"""

import os
import json
import asyncio
from typing import Dict, List, Any, Tuple
from utils.logging import logger
from utils.server_utils import (
    get_config_path,
    load_server_config,
    save_server_config,
    load_calendars,
    save_calendars
)

# Task tracking for background operations
_background_tasks = {}

def get_admins_file(server_id: int) -> str:
    """Get the path to the admins file for a server."""
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "servers", str(server_id), "admins.json")

def load_server_config(server_id: int) -> Dict[str, Any]:
    """Load server-specific configuration from config.json."""
    config_path = get_config_path(server_id)
    try:
        if os.path.exists(config_path):
            with open(config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
    except json.JSONDecodeError:
        logger.warning(f"Invalid JSON in config for server {server_id}")
    except Exception as e:
        logger.exception(f"Error loading config for server {server_id}: {e}")
    return {"calendars": [], "admins": []}  # Default structure

def save_server_config(server_id: int, config: Dict[str, Any]) -> bool:
    """Save server-specific configuration to config.json."""
    config_path = get_config_path(server_id)
    try:
        os.makedirs(os.path.dirname(config_path), exist_ok=True)
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        logger.exception(f"Error saving config for server {server_id}: {e}")
        return False

def add_calendar(server_id: int, calendar_data: Dict) -> Tuple[bool, str]:
    """Add a calendar to the server's config.json."""
    config = load_server_config(server_id)
    if any(cal.get("id") == calendar_data["id"] for cal in config["calendars"]):
        return False, f"Calendar already exists: {calendar_data['id']}"
    config["calendars"].append(calendar_data)
    if save_server_config(server_id, config):
        return True, f"Added calendar {calendar_data.get('name', 'Unnamed')} successfully."
    return False, "Failed to save updated config."

def remove_calendar(server_id: int, calendar_id: str) -> Tuple[bool, str]:
    """Remove a calendar from the server's config.json."""
    config = load_server_config(server_id)
    updated_calendars = [cal for cal in config["calendars"] if cal["id"] != calendar_id]
    if len(updated_calendars) == len(config["calendars"]):
        return False, "Calendar not found."
    config["calendars"] = updated_calendars
    if save_server_config(server_id, config):
        return True, "Calendar successfully removed."
    return False, "Failed to save updated config."

def load_admins(server_id: int) -> List[str]:
    """Load the list of admin user IDs for a server."""
    admin_file = get_admins_file(server_id)
    try:
        if os.path.exists(admin_file):
            with open(admin_file, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        logger.exception(f"Error loading admins for server {server_id}: {e}")
    return []

def save_admins(server_id: int, admin_ids: List[str]) -> bool:
    """Save the list of admin user IDs for a server."""
    admin_file = get_admins_file(server_id)
    try:
        with open(admin_file, 'w', encoding='utf-8') as f:
            json.dump(admin_ids, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        logger.error(f"Failed to save admins for server {server_id}: {e}")
        return False

def add_admin_user(server_id: int, user_id: str) -> Tuple[bool, str]:
    """
    Add a user as an admin for notifications.

    Args:
        server_id: The Discord server ID
        user_id: The Discord user ID to add as admin

    Returns:
        tuple: (success, message)
    """
    admin_ids = load_admins(server_id)
    if user_id not in admin_ids:
        admin_ids.append(user_id)
        if save_admins(server_id, admin_ids):
            return True, f"Added user ID {user_id} as admin."
        else:
            return False, "Failed to save admin list."
    return False, f"User ID {user_id} is already an admin."

def remove_admin_user(server_id: int, user_id: str) -> Tuple[bool, str]:
    """
    Remove a user from admin notifications.

    Args:
        server_id: The Discord server ID
        user_id: The Discord user ID to remove

    Returns:
        tuple: (success, message)
    """
    admin_ids = load_admins(server_id)
    if user_id in admin_ids:
        admin_ids.remove(user_id)
        if save_admins(server_id, admin_ids):
            return True, f"Removed user ID {user_id} from admins."
        else:
            return False, "Failed to save admin list."
    return False, f"User ID {user_id} is not an admin."