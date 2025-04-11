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
)
# Removing the circular import
# from bot.events import load_calendars_from_server_configs as load_calendars

# Define the server config directory path
SERVER_CONFIG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "servers")

# Task tracking for background operations
_background_tasks = {}

# Create a placeholder for post-configuration actions
_calendar_reload_callbacks = []

def register_calendar_reload_callback(callback):
    """Register a function to be called when calendars are modified"""
    if callable(callback) and callback not in _calendar_reload_callbacks:
        _calendar_reload_callbacks.append(callback)

def _trigger_calendar_reload():
    """Trigger all registered callbacks to reload calendars"""
    for callback in _calendar_reload_callbacks:
        try:
            callback()
        except Exception as e:
            logger.exception(f"Error in calendar reload callback: {e}")

def get_admins_file(server_id: int) -> str:
    """
    Get the path to the admins file for a server.
    Uses the same path logic as get_config_path for consistency.
    """
    # First try Docker volume path
    docker_path = os.path.join("/data", "servers", str(server_id), "admins.json")
    docker_dir = os.path.dirname(docker_path)
    
    # Test if Docker path is writable
    try:
        if not os.path.exists(docker_dir):
            os.makedirs(docker_dir, exist_ok=True)
        if os.access(docker_dir, os.W_OK):
            return docker_path
    except (PermissionError, OSError):
        pass  # Will try fallback

    # Fall back to local path
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
        _trigger_calendar_reload()  # Trigger reload callback
        return True, f"Added calendar {calendar_data.get('name', 'Unnamed')} successfully."
    return False, "Failed to save updated config."

def remove_calendar(server_id: int, calendar_id: str) -> Tuple[bool, str]:
    """Remove a calendar from the server's config.json."""
    config = load_server_config(server_id)
    
    # Log what we're looking for and what we have
    logger.debug(f"Trying to remove calendar with ID: {calendar_id}")
    logger.debug(f"Available calendars: {[cal.get('id', 'unknown') for cal in config.get('calendars', [])]}")
    
    # Check if calendar exists before removal
    calendar_exists = False
    for cal in config.get("calendars", []):
        if cal.get("id") == calendar_id:
            calendar_exists = True
            break
    
    if not calendar_exists:
        logger.warning(f"Calendar with ID '{calendar_id}' not found in server {server_id} config")
        return False, "Calendar not found."
    
    # Remove the calendar
    config["calendars"] = [cal for cal in config.get("calendars", []) if cal.get("id") != calendar_id]
    
    # Save the config and trigger reload
    if save_server_config(server_id, config):
        logger.info(f"Successfully removed calendar {calendar_id} from server {server_id}")
        _trigger_calendar_reload()  # Trigger reload callback
        return True, "Calendar successfully removed."
    
    logger.error(f"Failed to save config after removing calendar {calendar_id} from server {server_id}")
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

def get_all_server_ids() -> List[int]:
    """Get a list of all server IDs that have configuration files."""
    try:
        if not os.path.exists(SERVER_CONFIG_DIR):
            logger.warning(f"Server config directory does not exist: {SERVER_CONFIG_DIR}")
            return []
            
        server_ids = []
        for entry in os.listdir(SERVER_CONFIG_DIR):
            # Check if the entry name is a digit (server IDs are numeric)
            if entry.isdigit():
                full_path = os.path.join(SERVER_CONFIG_DIR, entry)
                
                # Check if it's a directory
                if os.path.isdir(full_path):
                    config_file = os.path.join(full_path, "config.json")
                    
                    # Check if config.json exists in the directory
                    if os.path.exists(config_file):
                        logger.debug(f"Found server config for ID: {entry}")
                        server_ids.append(int(entry))
                    else:
                        logger.debug(f"Directory {entry} exists but has no config.json")
        
        logger.info(f"Found {len(server_ids)} server configurations")
        return server_ids
    except Exception as e:
        logger.exception(f"Error listing server configurations: {e}")
        return []

def get_admin_user_ids(server_id: int) -> List[str]:
    """Get the list of admin user IDs for a server."""
    return load_admins(server_id)

def is_superadmin(server_id: int, user_id: str) -> bool:
    """
    Check if a user is a superadmin (server owner) for a server.
    
    Args:
        server_id: The Discord server ID
        user_id: The Discord user ID to check
        
    Returns:
        bool: True if the user is a superadmin, False otherwise
    """
    config = load_server_config(server_id)
    return config.get("owner_id") == user_id