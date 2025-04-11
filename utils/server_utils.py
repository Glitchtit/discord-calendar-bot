import os
import json
import logging
import re
import requests
from threading import Lock
from typing import Dict, List, Any, Optional, Tuple
from pathlib import Path

# Configure logger
logger = logging.getLogger("calendarbot")

_load_lock = Lock()
_save_lock = Lock()

# Path constants
DOCKER_DATA_DIR = "/data"
LOCAL_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")

# Create required directories if they don't exist
try:
    os.makedirs(os.path.join(LOCAL_DATA_DIR, "servers"), exist_ok=True)
except Exception as e:
    logger.warning(f"Failed to create server config directory: {e}")
    # Fallback to a different directory if needed
    fallback_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
    os.makedirs(fallback_dir, exist_ok=True)
    logger.info(f"Using fallback server config directory: {fallback_dir}")

def get_config_path(server_id: int) -> str:
    """
    Get the path to a server's configuration file.
    First tries the Docker volume path, then falls back to local path.
    """
    # First try Docker volume path
    docker_path = os.path.join(DOCKER_DATA_DIR, "servers", str(server_id), "config.json")
    docker_dir = os.path.dirname(docker_path)
    
    # Test if Docker path is writable
    try:
        if not os.path.exists(docker_dir):
            os.makedirs(docker_dir, exist_ok=True)
        if os.access(docker_dir, os.W_OK):
            return docker_path
    except (PermissionError, OSError):
        logger.debug(f"Docker path {docker_dir} not writable, using local path instead")

    # Fall back to local path
    return os.path.join(LOCAL_DATA_DIR, "servers", str(server_id), "config.json")

def load_server_config(server_id: int) -> Dict[str, Any]:
    """Load server-specific configuration from JSON file."""
    config_path = get_config_path(server_id)
    try:
        with _load_lock:
            config_dir = os.path.dirname(config_path)
            os.makedirs(config_dir, exist_ok=True)
            
            if os.path.exists(config_path):
                with open(config_path, "r", encoding="utf-8") as f:
                    return json.load(f)
    except json.JSONDecodeError:
        logger.warning(f"Invalid JSON in config for server {server_id}")
    except Exception as e:
        logger.exception(f"Config load error for {server_id}: {e}")
    
    # Return default config if loading fails
    return {"calendars": [], "user_mappings": {}}

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

def get_all_server_ids() -> List[int]:
    """Get a list of all server IDs that have configuration files.
    Checks both Docker and local paths for server configurations.
    """
    server_ids = set()  # Use a set to avoid duplicates
    
    # Check Docker path first
    try:
        docker_base_dir = os.path.join(DOCKER_DATA_DIR, "servers")
        if os.path.exists(docker_base_dir):
            for entry in os.listdir(docker_base_dir):
                full_path = os.path.join(docker_base_dir, entry)
                if entry.isdigit() and os.path.isdir(full_path):
                    config_file = os.path.join(full_path, "config.json")
                    if os.path.exists(config_file):
                        server_ids.add(int(entry))
    except Exception as e:
        logger.warning(f"Error listing Docker server configurations: {e}")
    
    # Then check local path
    try:
        local_base_dir = os.path.join(LOCAL_DATA_DIR, "servers")
        if os.path.exists(local_base_dir):
            for entry in os.listdir(local_base_dir):
                full_path = os.path.join(local_base_dir, entry)
                if entry.isdigit() and os.path.isdir(full_path):
                    config_file = os.path.join(full_path, "config.json")
                    if os.path.exists(config_file):
                        server_ids.add(int(entry))
    except Exception as e:
        logger.warning(f"Error listing local server configurations: {e}")
    
    return list(server_ids)

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
