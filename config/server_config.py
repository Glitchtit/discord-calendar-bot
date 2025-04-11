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
from utils.logging import logger
from config.calendar_config import CalendarConfig

# Import utilities from server_utils rather than redefining the same functions
from utils.server_utils import (
    load_server_config,
    save_server_config, 
    get_all_server_ids,
    detect_calendar_type,
    migrate_env_config_to_server
)

# Define the server config directory for reference
SERVER_CONFIG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'servers')
os.makedirs(SERVER_CONFIG_DIR, exist_ok=True)

# Task tracking for background operations
_background_tasks = {}

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
            
            # Set up real-time subscription in background with improved error handling
            async def setup_subscription():
                try:
                    from utils.calendar_sync import subscribe_calendar
                    await subscribe_calendar(calendar_data)
                    logger.info(f"Successfully subscribed to updates for calendar {calendar_data.get('id')}")
                except Exception as e:
                    logger.error(f"Failed to subscribe to calendar updates: {e}")
                    # Consider notifying an admin here if critical
            
            # Create and monitor the background task
            task_key = f"add_calendar_{server_id}_{calendar_data.get('id', 'unknown')}"
            task = asyncio.create_task(setup_subscription())
            _background_tasks[task_key] = task
            
            # Set up a callback to remove the task when done and log any errors
            def task_done_callback(task):
                try:
                    # Check if the task raised any exceptions
                    if task.exception():
                        logger.error(f"Background task {task_key} failed: {task.exception()}")
                except asyncio.CancelledError:
                    logger.warning(f"Task {task_key} was cancelled")
                except Exception as e:
                    logger.exception(f"Error handling task completion: {e}")
                finally:
                    # Remove the task from tracking
                    if task_key in _background_tasks:
                        del _background_tasks[task_key]
            
            task.add_done_callback(task_done_callback)
            
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
                
                # Unsubscribe from real-time updates in background with improved error handling
                if removed_calendar:
                    # Add server_id to the calendar data for reference if not present
                    removed_calendar["server_id"] = server_id
                    
                    async def cancel_subscription():
                        try:
                            from utils.calendar_sync import unsubscribe_calendar
                            await unsubscribe_calendar(removed_calendar)
                            logger.info(f"Successfully unsubscribed from calendar {calendar_id}")
                        except Exception as e:
                            logger.error(f"Failed to unsubscribe from calendar updates: {e}")
                    
                    # Create and monitor the background task
                    task_key = f"remove_calendar_{server_id}_{calendar_id}"
                    task = asyncio.create_task(cancel_subscription())
                    _background_tasks[task_key] = task
                    
                    # Set up a callback to remove the task when done and log any errors
                    def task_done_callback(task):
                        try:
                            # Check if the task raised any exceptions
                            if task.exception():
                                logger.error(f"Background task {task_key} failed: {task.exception()}")
                        except asyncio.CancelledError:
                            logger.warning(f"Task {task_key} was cancelled")
                        except Exception as e:
                            logger.exception(f"Error handling task completion: {e}")
                        finally:
                            # Remove the task from tracking
                            if task_key in _background_tasks:
                                del _background_tasks[task_key]
                    
                    task.add_done_callback(task_done_callback)
                
                return True, "Calendar successfully removed."
            else:
                return False, "Failed to save configuration after removing calendar."
        else:
            return False, "Calendar not found in configuration."
    except Exception as e:
        logger.exception(f"Error removing calendar: {e}")
        return False, f"Error removing calendar: {str(e)}"

async def check_background_tasks() -> Dict[str, str]:
    """
    Check the status of any currently running background tasks.
    
    Returns:
        Dictionary with task keys and their status
    """
    result = {}
    for key, task in list(_background_tasks.items()):
        if task.done():
            if task.exception():
                result[key] = f"Failed: {task.exception()}"
            else:
                result[key] = "Completed"
            # Clean up completed tasks
            del _background_tasks[key]
        elif task.cancelled():
            result[key] = "Cancelled"
            del _background_tasks[key]
        else:
            result[key] = "Running"
    
    return result

def get_admin_user_ids(server_id: int) -> list:
    """
    Get list of admin user IDs for a specific server, including the server owner as superadmin.

    Args:
        server_id: The Discord server ID

    Returns:
        List of user IDs that should receive admin notifications
    """
    config = load_server_config(server_id)
    admin_ids = set(config.get("admin_user_ids", []))

    # Add the server owner as a superadmin
    if "owner_id" in config:
        admin_ids.add(str(config["owner_id"]))

    return list(admin_ids)

def is_superadmin(server_id: int, user_id: str) -> bool:
    """
    Check if a user is the superadmin (server owner).

    Args:
        server_id: The Discord server ID
        user_id: The Discord user ID to check

    Returns:
        True if the user is the server owner, False otherwise
    """
    config = load_server_config(server_id)
    return str(config.get("owner_id")) == str(user_id)

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