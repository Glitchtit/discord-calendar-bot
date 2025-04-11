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
    get_calendars_path,
    load_server_config,
    save_server_config,
    load_calendars,
    save_calendars
)

# Task tracking for background operations
_background_tasks = {}

# Admin configuration directory
ADMIN_CONFIG_DIR = os.path.join(os.path.dirname(get_config_path(0)), 'admins')
os.makedirs(ADMIN_CONFIG_DIR, exist_ok=True)

def add_calendar(server_id: int, calendar_data: Dict) -> Tuple[bool, str]:
    """
    Add a calendar to a server's calendars file.

    Args:
        server_id: Discord server ID
        calendar_data: Calendar data including type, id, name, user_id

    Returns:
        tuple: (success, message)
    """
    try:
        # Validate required fields
        required_fields = ['type', 'id']
        for field in required_fields:
            if field not in calendar_data:
                return False, f"Missing required field: {field}"

        # Load existing calendars
        calendars = load_calendars(server_id)

        # Check for duplicate calendar
        if any(existing.get("id") == calendar_data["id"] for existing in calendars):
            return False, f"Calendar already exists: {calendar_data['id']}"

        # Add default values for optional fields
        calendar_data.setdefault("name", "Unnamed Calendar")

        # Add the calendar
        calendars.append(calendar_data)

        # Ensure the directory for server-specific data exists
        server_data_dir = os.path.join(os.path.dirname(get_config_path(server_id)), 'servers', str(server_id))
        os.makedirs(server_data_dir, exist_ok=True)

        # Update the path to save calendars
        calendars_file = os.path.join(server_data_dir, 'calendars.json')

        # Save calendars to the updated path
        with open(calendars_file, 'w', encoding='utf-8') as f:
            json.dump(calendars, f, ensure_ascii=False, indent=2)

        if save_calendars(server_id, calendars):
            logger.info(f"Added calendar {calendar_data.get('name')} to server {server_id}")
            return True, f"Added calendar {calendar_data.get('name')} successfully."
        else:
            return False, "Failed to save calendars."
    except Exception as e:
        logger.exception(f"Error adding calendar: {e}")
        return False, f"Error adding calendar: {str(e)}"

def remove_calendar(server_id: int, calendar_id: str) -> Tuple[bool, str]:
    """
    Remove a calendar from a server's calendars file.

    Args:
        server_id: Discord server ID
        calendar_id: ID of the calendar to remove

    Returns:
        tuple: (success, message)
    """
    try:
        # Load existing calendars
        calendars = load_calendars(server_id)

        # Filter out the calendar to remove
        updated_calendars = [cal for cal in calendars if cal["id"] != calendar_id]

        if len(updated_calendars) == len(calendars):
            return False, "Calendar not found."

        # Save updated calendars
        if save_calendars(server_id, updated_calendars):
            logger.info(f"Removed calendar {calendar_id} from server {server_id}")
            return True, "Calendar successfully removed."
        else:
            return False, "Failed to save updated calendars."
    except Exception as e:
        logger.exception(f"Error removing calendar: {e}")
        return False, f"Error removing calendar: {str(e)}"

def load_admins(server_id: int) -> List[str]:
    """Load the list of admin user IDs for a server."""
    admin_file = os.path.join(ADMIN_CONFIG_DIR, f"{server_id}_admins.json")
    try:
        if os.path.exists(admin_file):
            with open(admin_file, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        logger.exception(f"Error loading admins for server {server_id}: {e}")
    return []

def save_admins(server_id: int, admin_ids: List[str]) -> bool:
    """Save the list of admin user IDs for a server."""
    admin_file = os.path.join(ADMIN_CONFIG_DIR, f"{server_id}_admins.json")
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