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
import re
import requests
from typing import Dict, List, Any, Optional, Tuple
from log import logger

# Directory for server configuration files
SERVER_CONFIG_BASE = "/data"
SERVER_CONFIG_DIR = SERVER_CONFIG_BASE

# Create required directories if they don't exist
for path in [SERVER_CONFIG_BASE, os.path.dirname(SERVER_CONFIG_BASE)]:
    if not os.path.exists(path):
        try:
            os.makedirs(path, exist_ok=True)
            logger.info(f"Created directory: {path}")
        except Exception as e:
            logger.warning(f"Could not create directory {path}: {e}")

# Ensure the server configuration directory exists
try:
    os.makedirs(SERVER_CONFIG_BASE, exist_ok=True)
except Exception as e:
    logger.warning(f"Failed to create server config directory: {e}")
    # Fallback to local directory if /data is not writable
    SERVER_CONFIG_BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
    os.makedirs(SERVER_CONFIG_BASE, exist_ok=True)
    logger.info(f"Using fallback server config directory: {SERVER_CONFIG_BASE}")

def get_config_path(server_id: int) -> str:
    """Get the path to a server's configuration file."""
    return os.path.join(SERVER_CONFIG_BASE, str(server_id), "config.json")

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
        os.makedirs(os.path.dirname(config_path), exist_ok=True)
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
        for entry in os.listdir(SERVER_CONFIG_BASE):
            full_path = os.path.join(SERVER_CONFIG_BASE, entry)
            if entry.isdigit() and os.path.isdir(full_path):
                config_file = os.path.join(full_path, "config.json")
                if os.path.exists(config_file):
                    server_ids.append(int(entry))
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
    if url_or_id.startswith(('http://', 'https://')):
        if '.ics' in url_or_id.lower():
            return 'ics'
        try:
            r = requests.head(url_or_id, timeout=5)
            ct = r.headers.get('Content-Type', '').lower()
            if 'text/calendar' in ct or 'text/ical' in ct:
                return 'ics'
        except:
            pass
    
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

def migrate_env_config_to_server(server_id: int, calendar_sources: str, user_tag_mapping: str) -> Tuple[bool, str]:
    """
    Migrate environment variable configuration to server-specific configuration.
    
    This helper function is used for one-time migration from the deprecated
    environment variable approach to the new server-specific configuration.
    
    Args:
        server_id: Discord server ID to create configuration for
        calendar_sources: Value from CALENDAR_SOURCES environment variable
        user_tag_mapping: Value from USER_TAG_MAPPING environment variable
        
    Returns:
        (success, message): Tuple with migration status and message
    """
    if not calendar_sources and not user_tag_mapping:
        return False, "No legacy configuration found to migrate"
    
    # Load existing config or start with empty one
    config = load_server_config(server_id)
    changes_made = False
    
    # Process calendar sources (format: google:id:TAG or ics:url:TAG)
    if calendar_sources:
        calendars_added = 0
        for source in calendar_sources.split(','):
            source = source.strip()
            if not source:
                continue
                
            parts = source.split(':')
            if len(parts) < 3:
                continue
                
            cal_type, cal_id, tag = parts[0], parts[1], parts[2]
            
            # Skip if this calendar already exists
            if any(cal["id"] == cal_id for cal in config.get("calendars", [])):
                continue
                
            # Add the calendar
            calendar_entry = {
                "type": cal_type,
                "id": cal_id,
                "name": f"Migrated {cal_type.capitalize()} Calendar",
                "tag": tag
            }
            
            config.setdefault("calendars", []).append(calendar_entry)
            calendars_added += 1
            changes_made = True
    
    # Process user tag mappings (format: user_id:TAG)
    if user_tag_mapping:
        users_added = 0
        for mapping in user_tag_mapping.split(','):
            mapping = mapping.strip()
            if not mapping or ':' not in mapping:
                continue
                
            user_id, tag = mapping.split(':', 1)
            
            # Skip if mapping already exists
            if any(t == tag for t, uid in config.get("user_mappings", {}).items() if uid == user_id):
                continue
                
            config.setdefault("user_mappings", {})[tag] = user_id
            users_added += 1
            changes_made = True
    
    # Save if we made changes
    if changes_made and save_server_config(server_id, config):
        return True, f"Successfully migrated legacy configuration to server {server_id}"
    elif not changes_made:
        return False, "No new configuration to migrate"
    else:
        return False, "Failed to save migrated configuration"