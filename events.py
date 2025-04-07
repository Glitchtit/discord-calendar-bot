"""
events.py: Provides functions to fetch events from Google Calendars and ICS feeds,
handle caching of metadata, group calendars by tags, and parse ICS/Google events
into a unified format for the rest of the bot.
"""

import os
import json
import time
import ssl
import socket
import hashlib
import requests
import time
import random
from datetime import datetime, timedelta, date
from typing import Dict, List, Tuple, Optional, Any
from ics import Calendar as ICS_Calendar
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from environ import GOOGLE_APPLICATION_CREDENTIALS
from server_config import get_all_server_ids, load_server_config
from log import logger

# ╔════════════════════════════════════════════════════════════════════╗
# 🔐 Google Calendar API Setup
# ╚════════════════════════════════════════════════════════════════════╝
SERVICE_ACCOUNT_FILE = GOOGLE_APPLICATION_CREDENTIALS
SCOPES = ["https://www.googleapis.com/auth/calendar"]
EVENTS_FILE = "/data/events.json"

# In-memory cache
_calendar_metadata_cache = {}
_api_last_error_time = None
_api_error_count = 0
_API_BACKOFF_RESET = timedelta(minutes=30)
_MAX_API_ERRORS = 10

# Fallback directory for events if primary location is unavailable
FALLBACK_EVENTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

logger.debug(f"Loading Google credentials from: {SERVICE_ACCOUNT_FILE}")
try:
    credentials = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=SCOPES
    )
    service = build("calendar", "v3", credentials=credentials, cache_discovery=False)
    logger.info("Google Calendar service initialized.")
except Exception as e:
    logger.exception(f"Error initializing Google Calendar service: {e}")
    logger.debug("Debug: Verify GOOGLE_APPLICATION_CREDENTIALS is set correctly or the file exists.")
    service = None  # Will trigger fallback behavior in functions

# ╔════════════════════════════════════════════════════════════════════╗
# ║ 🧰 Service Account Info                                           ║
# ╚════════════════════════════════════════════════════════════════════╝
def get_service_account_email() -> str:
    """Get the service account email for sharing Google Calendars."""
    try:
        if not os.path.exists(SERVICE_ACCOUNT_FILE):
            return "Service account file not found"
            
        with open(SERVICE_ACCOUNT_FILE, 'r') as f:
            service_info = json.load(f)
            return service_info.get('client_email', 'Email not found in credentials')
    except Exception as e:
        logger.exception(f"Error reading service account email: {e}")
        return "Error reading service account info"

# ╔════════════════════════════════════════════════════════════════════╗
# ║ 👥 Server Config Based Calendar Loading                           ║
# ╚════════════════════════════════════════════════════════════════════╝
# Populated from server config files during bot startup
GROUPED_CALENDARS = {}
TAG_NAMES = {}
TAG_COLORS = {}
USER_TAG_MAP = {}

def get_name_for_tag(tag: str) -> str:
    """Get a display name for a tag with fallback to the tag itself."""
    if not tag:
        return "Unknown"
    return TAG_NAMES.get(tag, tag)

def get_color_for_tag(tag: str) -> int:
    """Get a color for a tag with fallback to a default gray."""
    if not tag:
        return 0x95a5a6  # Default gray
    return TAG_COLORS.get(tag, 0x95a5a6)

def load_calendars_from_server_configs():
    """Load all calendar configurations from server JSON files."""
    global GROUPED_CALENDARS, USER_TAG_MAP
    
    GROUPED_CALENDARS = {}
    USER_TAG_MAP = {}
    
    server_ids = get_all_server_ids()
    if not server_ids:
        logger.warning("No server configurations found. Please use /setup to configure calendars.")
        return
        
    logger.info(f"Loading calendar configurations from {len(server_ids)} servers...")
    
    for server_id in server_ids:
        config = load_server_config(server_id)
        calendars = config.get("calendars", [])
        user_mappings = config.get("user_mappings", {})
        
        # Add user mappings
        for tag, user_id in user_mappings.items():
            try:
                USER_TAG_MAP[int(user_id)] = tag
            except ValueError:
                logger.warning(f"Invalid user ID {user_id} in server {server_id} config")
        
        # Add calendars
        for calendar in calendars:
            tag = calendar.get("tag")
            if not tag:
                logger.warning(f"Calendar missing tag in server {server_id} config, skipping")
                continue
                
            # Convert to the format expected by the rest of the code
            calendar_meta = {
                "type": calendar.get("type", "google"),
                "id": calendar.get("id", ""),
                "name": calendar.get("name", "Unknown Calendar"),
                "tag": tag,
                "server_id": server_id
            }
            
            GROUPED_CALENDARS.setdefault(tag, []).append(calendar_meta)
    
    # Log summary of loaded calendars
    total_calendars = sum(len(cals) for cals in GROUPED_CALENDARS.values())
    logger.info(f"Loaded {total_calendars} calendars across {len(GROUPED_CALENDARS)} tags")
    
    for tag, calendars in GROUPED_CALENDARS.items():
        logger.debug(f"Tag {tag}: {len(calendars)} calendars")

# Remaining functions from events.py stay the same, but we'll change the old 
# parse_calendar_sources and get_user_tag_mapping functions to be deprecated

# ╔════════════════════════════════════════════════════════════════════╗
# ║ 🔁 retry_api_call                                                  ║
# ║ Helper to retry Google API calls with exponential backoff         ║
# ╚════════════════════════════════════════════════════════════════════╝
def retry_api_call(func, *args, max_retries=3, **kwargs):
    """Retry a Google API call with exponential backoff on transient errors."""
    global _api_last_error_time, _api_error_count
    
    # Check if we've had too many errors recently
    if _api_last_error_time and _api_error_count >= _MAX_API_ERRORS:
        # Check if enough time has passed to reset the counter
        if datetime.now() - _api_last_error_time > _API_BACKOFF_RESET:
            logger.info("API error count reset after backoff period")
            _api_error_count = 0
        else:
            logger.warning(f"Too many API errors ({_api_error_count}), backing off")
            return None
    
    last_exception = None
    
    for attempt in range(max_retries):
        try:
            return func(*args, **kwargs)
            
        except HttpError as e:
            status_code = e.resp.status
            
            # Don't retry on client errors except for 429 (rate limit)
            if status_code < 500 and status_code != 429:
                logger.warning(f"Non-retryable Google API error: {status_code} - {str(e)}")
                _api_error_count += 1
                _api_last_error_time = datetime.now()
                raise
                
            # For rate limits and server errors, retry with backoff
            backoff = (2 ** attempt) + random.uniform(0, 1)
            logger.warning(f"Retryable Google API error ({status_code}), attempt {attempt+1}/{max_retries}, backing off for {backoff:.2f}s: {str(e)}")
            time.sleep(backoff)
            last_exception = e
            
        except requests.exceptions.RequestException as e:
            # Network errors are retryable
            backoff = (2 ** attempt) + random.uniform(0, 1)
            logger.warning(f"Network error in API call, attempt {attempt+1}/{max_retries}, backing off for {backoff:.2f}s: {str(e)}")
            time.sleep(backoff)
            last_exception = e
            
        except Exception as e:
            # Other errors are not retried
            logger.exception(f"Unexpected error in API call: {e}")
            _api_error_count += 1
            _api_last_error_time = datetime.now()
            raise
    
    # If we've exhausted retries, record the error and return None
    if last_exception:
        _api_error_count += 1
        _api_last_error_time = datetime.now()
        logger.error(f"All {max_retries} retries failed for API call: {last_exception}")
        
    return None

# ╔════════════════════════════════════════════════════════════════════╗
# 📄 Metadata Caching
# ╚════════════════════════════════════════════════════════════════════╝
def fetch_google_calendar_metadata(calendar_id: str) -> Dict[str, Any]:
    """Fetch Google Calendar metadata with caching and robust error handling."""
    # Check cache first
    cache_key = f"google_{calendar_id}"
    if cache_key in _calendar_metadata_cache:
        logger.debug(f"Using cached metadata for calendar {calendar_id}")
        return _calendar_metadata_cache[cache_key]
    
    # Verify service is available
    if not service:
        logger.error(f"Google Calendar service not initialized, can't fetch metadata for {calendar_id}")
        return {"type": "google", "id": calendar_id, "name": calendar_id, "error": True}
    
    # First try to add the calendar to the list (might already be there)
    try:
        retry_api_call(
            service.calendarList().insert(body={"id": calendar_id}).execute
        )
    except Exception as e:
        # Ignore 'Already Exists' errors
        if "Already Exists" not in str(e):
            logger.warning(f"Couldn't subscribe to {calendar_id}: {e}")
    
    # Now try to get calendar details
    try:
        cal = retry_api_call(
            service.calendarList().get(calendarId=calendar_id).execute
        )
        
        if not cal:
            logger.warning(f"Failed to get metadata for calendar {calendar_id} after retries")
            result = {"type": "google", "id": calendar_id, "name": calendar_id, "error": True}
        else:
            # Extract calendar name, preferring the override name if available
            name = cal.get("summaryOverride") or cal.get("summary") or calendar_id
            timezone = cal.get("timeZone")
            color = cal.get("backgroundColor", "#95a5a6")
            
            result = {
                "type": "google", 
                "id": calendar_id, 
                "name": name,
                "timezone": timezone,
                "color": color
            }
            
            logger.debug(f"Loaded Google calendar metadata: {name}")
            
        # Cache the result
        _calendar_metadata_cache[cache_key] = result
        return result
        
    except Exception as e:
        logger.warning(f"Error getting metadata for Google calendar {calendar_id}: {e}")
        result = {"type": "google", "id": calendar_id, "name": calendar_id, "error": True}
        _calendar_metadata_cache[cache_key] = result
        return result
    
def fetch_ics_calendar_metadata(url: str) -> Dict[str, Any]:
    """Fetch ICS Calendar metadata with basic validation and fallback."""
    # Check cache first
    cache_key = f"ics_{url}"
    if cache_key in _calendar_metadata_cache:
        logger.debug(f"Using cached metadata for ICS calendar {url}")
        return _calendar_metadata_cache[cache_key]
    
    try:
        # Do a HEAD request to validate URL exists (with timeout)
        response = requests.head(url, timeout=5)
        response.raise_for_status()
        
        # Try to extract a meaningful name from the URL
        if "?" in url:
            url_parts = url.split("?")[0].split("/")
        else:
            url_parts = url.split("/")
            
        name = next((part for part in reversed(url_parts) if part), "ICS Calendar")
        
        # Decode URL-encoded characters
        if "%" in name:
            try:
                from urllib.parse import unquote
                name = unquote(name)
            except Exception:
                pass
                
        result = {"type": "ics", "id": url, "name": name}
        logger.debug(f"Loaded ICS calendar metadata: {name}")
        
        # Cache the result
        _calendar_metadata_cache[cache_key] = result
        return result
        
    except requests.exceptions.RequestException as e:
        logger.warning(f"Error validating ICS calendar URL {url}: {e}")
        result = {"type": "ics", "id": url, "name": "ICS Calendar", "error": True}
        _calendar_metadata_cache[cache_key] = result
        return result
    except Exception as e:
        logger.warning(f"Error getting metadata for ICS calendar {url}: {e}")
        result = {"type": "ics", "id": url, "name": "ICS Calendar", "error": True}
        _calendar_metadata_cache[cache_key] = result
        return result

# ╔════════════════════════════════════════════════════════════════════╗
# 📆 Google Calendar Event Fetching
# ╚════════════════════════════════════════════════════════════════════╝
def load_calendar_sources():
    """DEPRECATED: Use load_calendars_from_server_configs() instead.
    This function is kept for backward compatibility and now just calls
    the new server-config based loading function."""
    logger.warning("load_calendar_sources() is deprecated. Use load_calendars_from_server_configs() instead.")
    load_calendars_from_server_configs()
    return GROUPED_CALENDARS

# ╔════════════════════════════════════════════════════════════════════╗
# ║ 💾 Event Snapshot Persistence                                      ║
# ╚════════════════════════════════════════════════════════════════════╝
def load_previous_events():
    try:
        if os.path.exists(EVENTS_FILE):
            with open(EVENTS_FILE, "r", encoding="utf-8") as f:
                logger.debug("Loaded previous event snapshot from disk.")
                return json.load(f)
    except json.JSONDecodeError:
        logger.warning("Previous events file corrupted. Starting fresh.")
    except Exception as e:
        logger.exception(f"Error loading previous events: {e}")
    return {}

def save_current_events_for_key(key, events):
    try:
        logger.debug(f"Saving {len(events)} events under key: {key}")
        all_data = load_previous_events()
        all_data[key] = events
        with open(EVENTS_FILE, "w", encoding="utf-8") as f:
            json.dump(all_data, f, ensure_ascii=False)
        logger.info(f"Saved events for key '{key}'.")
    except Exception as e:
        logger.exception(f"Error saving events for key {key}: {e}")

# ╔════════════════════════════════════════════════════════════════════╗
# ║ 📆 Event Fetching                                                  ║
# ║ Retrieves events from Google or ICS sources                        ║
# ╚════════════════════════════════════════════════════════════════════╝
def get_google_events(start_date, end_date, calendar_id):
    try:
        start_utc = start_date.isoformat() + "T00:00:00Z"
        end_utc = end_date.isoformat() + "T23:59:59Z"
        logger.debug(f"Fetching Google events for calendar {calendar_id} from {start_utc} to {end_utc}")
        result = service.events().list(
            calendarId=calendar_id,
            timeMin=start_utc,
            timeMax=end_utc,
            singleEvents=True,
            orderBy="startTime"
        ).execute()
    except Exception as e:
        logger.exception(f"Error fetching Google events from calendar {calendar_id}: {e}")
        return []

def get_ics_events(start_date, end_date, url):
    try:
        logger.debug(f"Fetching ICS events from {url}")
        response = requests.get(url)
        response.encoding = 'utf-8'
        cal = ICS_Calendar(response.text)
        events = []
        for e in cal.events:
            if start_date <= e.begin.date() <= end_date:
                id_source = f"{e.name}|{e.begin}|{e.end}|{e.location or ''}"
                event = {
                    "summary": e.name,
                    "start": {"dateTime": e.begin.isoformat()},
                    "end": {"dateTime": e.end.isoformat()},
                    "location": e.location or "",
                    "description": e.description or "",
                    "id": hashlib.md5(id_source.encode("utf-8")).hexdigest()
                }
                events.append(event)

        seen_fps = set()
        deduped = []
        for e in events:
            fp = compute_event_fingerprint(e)
            if fp not in seen_fps:
                seen_fps.add(fp)
                deduped.append(e)
        logger.debug(f"Deduplicated to {len(deduped)} ICS events")
        return deduped
    except Exception as e:
        logger.exception(f"Error fetching/parsing ICS calendar: {url}")
        return []

# ╔════════════════════════════════════════════════════════════════════╗
# 📡 Unified Event Fetching Interface
# ╚════════════════════════════════════════════════════════════════════╝

def get_events(
    source_meta: Dict[str, str],
    start_date: date,
    end_date: date
) -> List[Dict[str, Any]]:
    """
    Fetches events from a given calendar source (Google or ICS) within
    the specified date range.

    Args:
        source_meta: A dictionary describing the calendar source,
            e.g. { "type": "google", "id": <calendar ID>, ... }.
        start_date: The start date of the requested range.
        end_date: The end date of the requested range.

    Returns:
        A list of event dictionaries from this source in a unified format.
    """
    logger.debug(f"[events.py] ⏳ Fetching events from {source_meta['name']} ({source_meta['type']})")
    if source_meta["type"] == "google":
        return get_google_events(start_date, end_date, source_meta["id"])
    elif source_meta["type"] == "ics":
        return get_ics_events(start_date, end_date, source_meta["id"])
    return []

# ╔════════════════════════════════════════════════════════════════════╗
# ║ 🧬 compute_event_fingerprint                                       ║
# ║ Generates a stable hash for an event's core details               ║
# ╚════════════════════════════════════════════════════════════════════╝
def compute_event_fingerprint(event: dict) -> str:
    try:
        def normalize_time(val: str) -> str:
            if "Z" in val:
                val = val.replace("Z", "+00:00")
            dt = datetime.fromisoformat(val)
            return dt.isoformat(timespec="minutes")

        def clean(text: str) -> str:
            return " ".join(text.strip().split())

        summary = clean(event.get("summary", ""))
        location = clean(event.get("location", ""))
        description = clean(event.get("description", ""))

        start_raw = event["start"].get("dateTime", event["start"].get("date", ""))
        end_raw = event["end"].get("dateTime", event["end"].get("date", ""))
        start = normalize_time(start_raw)
        end = normalize_time(end_raw)

        trimmed = {
            "summary": summary,
            "start": start,
            "end": end,
            "location": location,
            "description": description
        }

        normalized_json = json.dumps(trimmed, sort_keys=True)
        return hashlib.md5(normalized_json.encode("utf-8")).hexdigest()
    except Exception as e:
        logger.exception(f"Error computing event fingerprint: {e}")
        return ""

# ╔════════════════════════════════════════════════════════════════════╗
# ║ ⚠️ Legacy Functions (Deprecated)                                   ║
# ╚════════════════════════════════════════════════════════════════════╝
def parse_calendar_sources():
    """DEPRECATED: Use load_calendars_from_server_configs() instead.
    
    This function previously parsed CALENDAR_SOURCES environment variable,
    but is now replaced by server-specific configuration via /setup command.
    Returns an empty list for backward compatibility.
    """
    logger.warning("parse_calendar_sources() is deprecated. Use server-specific configuration with /setup command instead.")
    return []

def get_user_tag_mapping():
    """DEPRECATED: Use server-specific user mappings instead.
    
    This function previously parsed USER_TAG_MAPPING environment variable,
    but is now replaced by per-server user mappings in server config files.
    Returns an empty dict for backward compatibility.
    """
    logger.warning("get_user_tag_mapping() is deprecated. User-tag mappings are now stored in server configurations.")
    return {}

def resolve_tag_mappings():
    """DEPRECATED: Tag mappings are now managed per server.
    
    This function previously resolved tag mappings from environment variables,
    but is now handled during server config loading.
    """
    logger.warning("resolve_tag_mappings() is deprecated. Tag mappings are now resolved during server config loading.")
    return

# ╔════════════════════════════════════════════════════════════════════╗
# ║ 🔄 Reload Functions                                                ║
# ║ Functions to handle reloading after setup changes                  ║
# ╚════════════════════════════════════════════════════════════════════╝
async def reinitialize_events():
    """
    Re-initializes the event snapshots after calendar configuration changes.
    This should be called after /setup or /reload commands to ensure events
    are properly loaded into /data/events.json.
    """
    from tasks import initialize_event_snapshots
    
    # First, reload calendar configurations
    load_calendars_from_server_configs()
    
    # Then initialize event snapshots
    logger.info("Re-initializing event snapshots after configuration change")
    await initialize_event_snapshots()
    
    return True

# Initialize calendars on module load
load_calendars_from_server_configs()
