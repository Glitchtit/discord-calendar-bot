import os
import json
import re
from typing import Dict, List, Any, Optional, Tuple
from log import logger

# Directory for server configuration files
SERVER_CONFIG_DIR = "/data/servers"

# Create required directories if they don't exist
for path in [SERVER_CONFIG_DIR, os.path.dirname(SERVER_CONFIG_DIR)]:
    if not os.path.exists(path):
        try:
            os.makedirs(path, exist_ok=True)
            logger.info(f"Created directory: {path}")
        except Exception as e:
            logger.warning(f"Could not create directory {path}: {e}")

# Ensure the server configuration directory exists
try:
    os.makedirs(SERVER_CONFIG_DIR, exist_ok=True)
except Exception as e:
    logger.warning(f"Failed to create server config directory: {e}")
    # Fallback to local directory if /data is not writable
    SERVER_CONFIG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "servers")
    os.makedirs(SERVER_CONFIG_DIR, exist_ok=True)

def get_config_path(server_id: int) -> str:
    """Get the path to a server's configuration file."""
    return os.path.join(SERVER_CONFIG_DIR, f"{server_id}.json")

def load_server_config(server_id: int) -> Dict[str, Any]:
    """Load configuration for a specific server."""
    config_path = get_config_path(server_id)
    
    try:
        if os.path.exists(config_path):
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
                logger.debug(f"Loaded configuration for server {server_id}")
                return config
    except json.JSONDecodeError:
        logger.warning(f"Invalid JSON in config file for server {server_id}")
    except Exception as e:
        logger.exception(f"Error loading server config: {e}")
    
    # Return default config if file doesn't exist or has errors
    return {
        "calendars": [],
        "user_mappings": {}
    }

def save_server_config(server_id: int, config: Dict[str, Any]) -> bool:
    """Save configuration for a specific server."""
    config_path = get_config_path(server_id)
    
    try:
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        logger.info(f"Saved configuration for server {server_id}")
        return True
    except Exception as e:
        logger.exception(f"Error saving server config: {e}")
        return False

def add_calendar(server_id: int, calendar_url: str, user_id: str, display_name: str = "") -> Tuple[bool, str]:
    """Add a calendar to a server's configuration.
    
    Args:
        server_id: Discord server ID
        calendar_url: URL or ID of the calendar
        user_id: Discord User ID to associate with this calendar
        display_name: Optional display name for the calendar
    
    Returns:
        (success, message): Tuple with success status and message
    """
    config = load_server_config(server_id)
    
    # Detect calendar type (Google or ICS)
    calendar_type = detect_calendar_type(calendar_url)
    if not calendar_type:
        return False, "Invalid calendar URL format. Please provide a valid Google Calendar ID or ICS URL."
    
    # Generate a tag for the user if they don't have one
    user_id_str = str(user_id)
    user_tag = None
    
    for tag, mapped_id in config.get("user_mappings", {}).items():
        if mapped_id == user_id_str:
            user_tag = tag
            break
    
    if not user_tag:
        # Create a new tag based on username if possible, otherwise use USER_{id}
        user_tag = f"USER_{user_id_str[-4:]}"  # Use last 4 digits of user ID
        config.setdefault("user_mappings", {})[user_tag] = user_id_str
    
    # Add calendar to config
    calendar_entry = {
        "type": calendar_type,
        "id": calendar_url,
        "name": display_name or f"{calendar_type.capitalize()} Calendar",
        "tag": user_tag
    }
    
    # Check for duplicates
    for existing in config.get("calendars", []):
        if existing["id"] == calendar_url:
            return False, "This calendar is already added to the server."
    
    config.setdefault("calendars", []).append(calendar_entry)
    
    if save_server_config(server_id, config):
        return True, f"Calendar successfully added and assigned to tag {user_tag}."
    else:
        return False, "Failed to save configuration. Please try again."

def remove_calendar(server_id: int, calendar_id: str) -> Tuple[bool, str]:
    """Remove a calendar from a server's configuration."""
    config = load_server_config(server_id)
    
    calendars = config.get("calendars", [])
    initial_count = len(calendars)
    
    config["calendars"] = [cal for cal in calendars if cal["id"] != calendar_id]
    
    if len(config["calendars"]) < initial_count:
        if save_server_config(server_id, config):
            return True, "Calendar successfully removed."
        else:
            return False, "Failed to save configuration after removing calendar."
    else:
        return False, "Calendar not found in configuration."

def get_all_server_ids() -> List[int]:
    """Get a list of all server IDs that have configuration files."""
    try:
        server_ids = []
        for filename in os.listdir(SERVER_CONFIG_DIR):
            if filename.endswith('.json'):
                try:
                    server_id = int(filename[:-5])  # Remove .json extension
                    server_ids.append(server_id)
                except ValueError:
                    # Not a valid server ID filename
                    pass
        return server_ids
    except Exception as e:
        logger.exception(f"Error listing server configurations: {e}")
        return []

def detect_calendar_type(url_or_id: str) -> Optional[str]:
    """Detect if a calendar URL/ID is Google or ICS format.
    
    Returns:
        'google' or 'ics' or None if format is unrecognized
    """
    # Check for ICS URL format
    if url_or_id.startswith(('http://', 'https://')) and '.ics' in url_or_id.lower():
        return 'ics'
    
    # Google Calendar ID formats:
    # - email format: xxx@group.calendar.google.com
    # - standard format: alphanumeric_with_dashes@group.calendar.google.com
    google_pattern = re.compile(r'^[a-zA-Z0-9._-]+@(group\.calendar\.google\.com|gmail\.com)$')
    if google_pattern.match(url_or_id) or url_or_id.endswith('calendar.google.com'):
        return 'google'
    
    # If it has googleapis.com in the URL, it's likely a Google calendar
    if 'googleapis.com' in url_or_id:
        return 'google'
    
    # Handle direct calendar ID without domain
    if re.match(r'^[a-zA-Z0-9_-]+$', url_or_id):
        return 'google'  # Assume Google format if it's just alphanumeric+symbols
    
    return None  # Unknown format