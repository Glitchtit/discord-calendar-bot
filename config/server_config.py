"""
server_config.py: Server-specific configuration management for the calendar bot.

This module replaces the previous environment variable-based configuration approach
with a server-specific JSON file storage system. Each Discord server now has its own
configuration file stored in the /data/servers directory.

This enables:
- Per-server calendar configurations
- Server-specific user-tag mappings  
- Independent setup across different Discord servers
"""

import os
import json
from typing import Dict, List, Any, Optional, Tuple
import logging
import asyncio
from utils.server_utils import (
    load_server_config,
    save_server_config, 
    get_all_server_ids,
    detect_calendar_type,
    migrate_env_config_to_server
)
from config.calendar_config import CalendarConfig
from data_processing.data import (
    load_calendar_events,
    save_calendar_events,
    load_user_mappings,
    save_user_mappings
)

# Configure logger
logger = logging.getLogger("calendarbot")

def add_calendar(server_id: int, calendar_data: Dict) -> Tuple[bool, str]:
    """
    Add a calendar to a server's configuration with improved validation.
    
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
                
        # Load existing configuration
        config = load_server_config(server_id)
        
        # Initialize calendars list if not exists
        if "calendars" not in config:
            config["calendars"] = []
            
        # Check for duplicate calendar
        for existing in config["calendars"]:
            if existing.get("id") == calendar_data["id"]:
                return False, f"Calendar already exists: {calendar_data['id']}"
                
        # Add server_id to the calendar data for reference
        calendar_data["server_id"] = server_id
        
        # Add default values for optional fields
        if "name" not in calendar_data:
            calendar_data["name"] = "Unnamed Calendar"
        
        # Add to configuration
        config["calendars"].append(calendar_data)
        
        # Save configuration
        if save_server_config(server_id, config):
            logger.info(f"Added calendar {calendar_data.get('name')} to server {server_id}")
            
            # Set up real-time subscription in background
            asyncio.create_task(_subscribe_calendar(calendar_data))
            
            return True, f"Added calendar {calendar_data.get('name')} successfully."
        else:
            return False, "Failed to save configuration."
    except Exception as e:
        logger.exception(f"Error adding calendar: {e}")
        return False, f"Error adding calendar: {str(e)}"

def remove_calendar(server_id: int, calendar_id: str) -> Tuple[bool, str]:
    """
    Remove a calendar from a server's configuration.
    
    Args:
        server_id: Discord server ID
        calendar_id: ID of the calendar to remove
        
    Returns:
        tuple: (success, message)
    """
    try:
        # Load configuration
        config = load_server_config(server_id)
        
        # Validate config structure
        if not isinstance(config, dict):
            return False, "Invalid server configuration structure."

        # Find the calendar to remove
        calendars = config.get("calendars", [])
        initial_count = len(calendars)
        
        removed_calendar = None
        for cal in calendars:
            if cal["id"] == calendar_id:
                removed_calendar = cal
                break
                
        # Filter out the calendar
        config["calendars"] = [cal for cal in calendars if cal["id"] != calendar_id]
        
        # Check if we actually removed anything
        if len(config["calendars"]) < initial_count:
            if save_server_config(server_id, config):
                logger.info(f"Removed calendar {calendar_id} from server {server_id}")
                
                # Unsubscribe from real-time updates in background if we found the calendar
                if removed_calendar:
                    # Add server_id to the calendar data for reference
                    removed_calendar["server_id"] = server_id
                    asyncio.create_task(_unsubscribe_calendar(removed_calendar))
                
                return True, "Calendar successfully removed."
            else:
                return False, "Failed to save configuration after removing calendar."
        else:
            return False, "Calendar not found in configuration."
    except Exception as e:
        logger.exception(f"Error removing calendar: {e}")
        return False, f"Error removing calendar: {str(e)}"

async def _subscribe_calendar(calendar_data: Dict) -> None:
    """
    Subscribe to real-time updates for a calendar in the background.
    
    Args:
        calendar_data: Calendar data dictionary
    """
    try:
        from utils.calendar_sync import subscribe_calendar
        await subscribe_calendar(calendar_data)
    except Exception as e:
        logger.error(f"Error subscribing to calendar updates: {e}")

async def _unsubscribe_calendar(calendar_data: Dict) -> None:
    """
    Unsubscribe from real-time updates for a calendar in the background.
    
    Args:
        calendar_data: Calendar data dictionary
    """
    try:
        from utils.calendar_sync import unsubscribe_calendar
        await unsubscribe_calendar(calendar_data)
    except Exception as e:
        logger.error(f"Error unsubscribing from calendar updates: {e}")

def get_admin_user_ids() -> list:
    """
    Get list of admin user IDs from all server configurations.
    
    Returns:
        List of user IDs that should receive admin notifications
    """
    admin_ids = set()
    
    # Look through all server configs
    for server_id in get_all_server_ids():
        config = load_server_config(server_id)
        
        # Check for admin_user_ids in the config
        if "admin_user_ids" in config and isinstance(config["admin_user_ids"], list):
            for admin_id in config["admin_user_ids"]:
                admin_ids.add(str(admin_id))
        
        # Also add the server owner if specified
        if "owner_id" in config:
            admin_ids.add(str(config["owner_id"]))
    
    return list(admin_ids)

def add_admin_user(server_id: int, user_id: str) -> tuple:
    """
    Add a user as an admin for notifications.
    
    Args:
        server_id: The Discord server ID
        user_id: The Discord user ID to add as admin
        
    Returns:
        tuple: (success, message)
    """
    config = load_server_config(server_id)
    
    # Initialize the admin_user_ids list if it doesn't exist
    if "admin_user_ids" not in config:
        config["admin_user_ids"] = []
        
    # Convert to strings for consistency
    user_id = str(user_id)
        
    # Add the user if not already in the list
    if user_id not in config["admin_user_ids"]:
        config["admin_user_ids"].append(user_id)
        save_server_config(server_id, config)
        return True, f"Added user ID {user_id} as admin"
    else:
        return False, f"User ID {user_id} is already an admin"

def remove_admin_user(server_id: int, user_id: str) -> tuple:
    """
    Remove a user from admin notifications.
    
    Args:
        server_id: The Discord server ID
        user_id: The Discord user ID to remove
        
    Returns:
        tuple: (success, message)
    """
    config = load_server_config(server_id)
    user_id = str(user_id)
    
    # Check if the admin_user_ids list exists and user is in it
    if "admin_user_ids" in config and user_id in config["admin_user_ids"]:
        config["admin_user_ids"].remove(user_id)
        save_server_config(server_id, config)
        return True, f"Removed user ID {user_id} from admins"
    else:
        return False, f"User ID {user_id} is not an admin"