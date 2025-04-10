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
from utils import load_server_config  # Ensure this is imported from utils.py
from threading import Lock
from config.calendar_config import CalendarConfig

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

_save_lock = Lock()

def save_server_config(server_id: int, config: Dict[str, Any]) -> bool:
    """Save configuration for a specific server."""
    config_path = get_config_path(server_id)
    
    try:
        os.makedirs(os.path.dirname(config_path), exist_ok=True)
        with _save_lock:  # Ensure thread safety
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
        logger.info(f"Saved configuration for server {server_id}")
        return True
    except Exception as e:
        logger.exception(f"Error saving server config: {e}")
        return False

def add_calendar(server_id: int, calendar_data: Dict) -> bool:
    config = CalendarConfig(server_id)
    config.add_calendar(calendar_data)
    return True

def remove_calendar(server_id: int, calendar_id: str) -> Tuple[bool, str]:
    """Remove a calendar from a server's configuration."""
    config = load_server_config(server_id)
    
    # Validate config structure
    if not isinstance(config, dict):
        return False, "Invalid server configuration structure."

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
        'google', 'ics', or None if format is unrecognized
    """
    # Check for ICS URL format
    if url_or_id.startswith(('http://', 'https://')):
        # Check for .ics in the URL, even with non-standard ports
        if '.ics' in url_or_id.lower():
            return 'ics'
        
        # Fallback detection by checking content-type
        try:
            r = requests.head(url_or_id, timeout=5, allow_redirects=True)
            ct = r.headers.get('Content-Type', '').lower()
            if any(x in ct for x in ('text/calendar', 'text/ical', 'application/ics', 'application/calendar')):
                return 'ics'
        except Exception as e:
            logger.warning(f"Error detecting calendar type for URL {url_or_id}: {e}")

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

def migrate_env_config_to_server(server_id: int, calendar_sources: str, user_mapping: str) -> Tuple[bool, str]:
    """
    Migrate environment variable configuration to server-specific configuration.
    
    This helper function is used for one-time migration from the deprecated
    environment variable approach to the new server-specific configuration.
    
    Args:
        server_id: Discord server ID to create configuration for
        calendar_sources: Value from CALENDAR_SOURCES environment variable
        user_mapping: Value from USER_TAG_MAPPING environment variable
        
    Returns:
        (success, message): Tuple with migration status and message
    """
    if not calendar_sources and not user_mapping:
        return False, "No legacy configuration found to migrate"
    
    # Load existing config or start with empty one
    config = load_server_config(server_id)
    changes_made = False
    
    # Process calendar sources (format: google:id:user_id or ics:url:user_id)
    if calendar_sources:
        for source in calendar_sources.split(','):
            source = source.strip()
            if not source:
                continue
                
            parts = source.split(':')
            if len(parts) < 3:
                continue
                
            cal_type, cal_id, user_id = parts[0], parts[1], parts[2]
            
            # Skip if this calendar already exists
            if any(cal["id"] == cal_id for cal in config.get("calendars", [])):
                continue
                
            # Add the calendar
            calendar_entry = {
                "type": cal_type,
                "id": cal_id,
                "name": f"Migrated {cal_type.capitalize()} Calendar",
                "user_id": user_id
            }
            
            config.setdefault("calendars", []).append(calendar_entry)
            changes_made = True
    
    # Save if changes were made
    if changes_made and save_server_config(server_id, config):
        return True, f"Successfully migrated legacy configuration to server {server_id}"
    elif not changes_made:
        return False, "No new configuration to migrate"
    else:
        return False, "Failed to save migrated configuration"