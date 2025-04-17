"""
server_config.py: Server-specific configuration management for the calendar bot.

This module manages server-specific configurations, including calendars and admin settings.
Configurations are stored in JSON files under the /data/servers directory.
"""

import os
import json
import asyncio
from typing import Dict, List, Any, Tuple, Optional
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

def set_announcement_channel(server_id: int, channel_id: int) -> Tuple[bool, str]:
    """Set the announcement channel ID for the server."""
    config = load_server_config(server_id)
    config["announcement_channel_id"] = channel_id
    if save_server_config(server_id, config):
        logger.info(f"Set announcement channel for server {server_id} to {channel_id}")
        return True, "Announcement channel updated successfully."
    else:
        logger.error(f"Failed to save announcement channel for server {server_id}")
        return False, "Failed to save configuration."

def get_announcement_channel_id(server_id: int) -> Optional[int]:
    """Get the announcement channel ID for the server."""
    config = load_server_config(server_id)
    channel_id = config.get("announcement_channel_id")
    logger.debug(f"Retrieved announcement_channel_id for server {server_id}: {channel_id}") # Added debug log
    return channel_id

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
    """Save the list of admin user IDs for a server, ensuring the owner is included."""
    admin_file = get_admins_file(server_id)
    try:
        # Ensure owner_id is always included
        config = load_server_config(server_id)
        owner_id = config.get("owner_id")
        
        # Use a set for efficient handling and duplicate prevention
        admin_set = set(admin_ids)
        if owner_id:
            admin_set.add(str(owner_id)) # Ensure owner_id is a string
        else:
            logger.warning(f"Server {server_id} does not have an owner_id set in its main config.")
            
        # Convert back to list for saving
        final_admin_list = list(admin_set)
        
        # Ensure the directory exists
        os.makedirs(os.path.dirname(admin_file), exist_ok=True)
        
        with open(admin_file, 'w', encoding='utf-8') as f:
            json.dump(final_admin_list, f, ensure_ascii=False, indent=2)
        logger.debug(f"Saved admins for server {server_id}: {final_admin_list}")
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
            
        # Add more debugging information
        logger.debug(f"Searching for server configs in directory: {SERVER_CONFIG_DIR}")
        
        # Also check the Docker path
        docker_dir = "/data/servers"
        if os.path.exists(docker_dir):
            logger.debug(f"Docker server config directory exists: {docker_dir}")
            
            # List contents of Docker directory for debugging
            try:
                docker_contents = os.listdir(docker_dir)
                logger.debug(f"Docker directory contents: {docker_contents}")
                
                # Check individual server directories
                for entry in docker_contents:
                    if entry.isdigit():
                        server_dir = os.path.join(docker_dir, entry)
                        config_file = os.path.join(server_dir, "config.json")
                        if os.path.exists(config_file):
                            logger.debug(f"Found server config in Docker path: {config_file}")
            except Exception as e:
                logger.warning(f"Error reading Docker directory contents: {e}")
        else:
            logger.debug("Docker server config directory does not exist")
            
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
        
        # Now also check Docker path for server IDs
        if os.path.exists(docker_dir):
            for entry in os.listdir(docker_dir):
                if entry.isdigit():
                    docker_config_path = os.path.join(docker_dir, entry, "config.json")
                    if os.path.exists(docker_config_path):
                        server_id = int(entry)
                        if server_id not in server_ids:  # Avoid duplicates
                            logger.debug(f"Found additional server config in Docker path for ID: {entry}")
                            server_ids.append(server_id)
        
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