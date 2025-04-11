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
import pathlib
from datetime import datetime, timedelta, date
from typing import Dict, List, Tuple, Optional, Any
from ics import Calendar as ICS_Calendar
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from utils.logging import logger
from asyncio import Lock

# Removed unused imports
from utils.cache import event_cache
from config.server_config import load_server_config, get_all_server_ids
from config.server_config import save_server_config  # Added missing import
from config.server_config import register_calendar_reload_callback  # Add this import
from utils.environ import GOOGLE_APPLICATION_CREDENTIALS  # Added missing import

# We'll move the registration after the function is defined

# ╔════════════════════════════════════════════════════════════════════╗
# 🔐 Google Calendar API Setup
# ╚════════════════════════════════════════════════════════════════════╝
SERVICE_ACCOUNT_FILE = GOOGLE_APPLICATION_CREDENTIALS
SCOPES = ["https://www.googleapis.com/auth/calendar"]

def get_data_directory(server_id: int) -> pathlib.Path:
    """
    Get the appropriate data directory for a server with fallbacks.
    First tries Docker volume path, then local paths.
    """
    # Docker container path (primary location)
    docker_dir = pathlib.Path("/data") / "servers" / str(server_id)
    
    # Try to create/use Docker directory
    try:
        docker_dir.mkdir(parents=True, exist_ok=True)
        if os.access(docker_dir, os.W_OK):
            logger.debug(f"Using Docker volume path for server data: {docker_dir}")
            return docker_dir
    except (PermissionError, OSError):
        logger.debug(f"Docker path {docker_dir} not writable, trying fallbacks")
        
    # Local directory relative to this file
    local_dir = pathlib.Path(__file__).parent.parent / "data" / "servers" / str(server_id)
    try:
        local_dir.mkdir(parents=True, exist_ok=True)
        if os.access(local_dir, os.W_OK):
            logger.info(f"Using local data directory: {local_dir}")
            return local_dir
    except (PermissionError, OSError):
        logger.warning(f"Local path {local_dir} not writable, using temp directory")
        
    # Temp directory as last resort
    import tempfile
    temp_dir = pathlib.Path(tempfile.gettempdir()) / "discord-calendar-bot" / "servers" / str(server_id)
    try:
        temp_dir.mkdir(parents=True, exist_ok=True)
        logger.warning(f"Using temporary directory for data: {temp_dir}")
        return temp_dir
    except (PermissionError, OSError) as e:
        logger.error(f"Failed to create any data directory: {e}")
        # Return the original even though it might not work, to maintain API
        return docker_dir

def get_events_file(server_id: int) -> str:
    """
    Get the path to the events file for a server.
    Uses the same logic as get_data_directory to ensure consistency.
    """
    data_dir = get_data_directory(server_id)
    return str(data_dir / 'events.json')

# In-memory cache
_calendar_metadata_cache = {}
_api_last_error_time = None
_api_error_count = 0
_API_BACKOFF_RESET = timedelta(minutes=30)
_MAX_API_ERRORS = 10

logger.debug(f"Loading Google credentials from: {SERVICE_ACCOUNT_FILE}")
try:
    credentials = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=SCOPES
    )
    if not credentials:
        logger.error("No Google Credentials were loaded. Please check your config.")
        service = None
    else:
        service = build("calendar", "v3", credentials=credentials, cache_discovery=False)
        logger.info("Google Calendar service initialized.")
except Exception as e:
    logger.exception(f"Error initializing Google Calendar service: {e}")
    logger.debug("Debug: Verify GOOGLE_APPLICATION_CREDENTIALS is set correctly or the file exists.")
    service = None  # Will trigger fallback behavior in functions

# ╔════════════════════════════════════════════════════════════════════╗
# ║ 👥 Server Config Based Calendar Loading                           ║
# ╚════════════════════════════════════════════════════════════════════╝
# Populated from server config files during bot startup
GROUPED_CALENDARS = {}
TAG_NAMES = {}
TAG_COLORS = {}
USER_TAG_MAP = {}

def get_service_account_email() -> str:
    """
    Returns the email address associated with the Google service account.
    This is used for sharing calendars with the service account.
    
    Returns:
        The service account email or an empty string if unavailable.
    """
    try:
        if not credentials:
            logger.error("No Google credentials available to extract service account email")
            return ""
        
        # Extract email from the service account credentials
        email = credentials.service_account_email
        logger.debug(f"Service account email: {email}")
        return email
    except Exception as e:
        logger.exception(f"Error retrieving service account email: {e}")
        return ""

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
    global GROUPED_CALENDARS
    GROUPED_CALENDARS.clear()  # Clear existing calendars

    # Track problematic calendars for logging
    missing_user_id_count = 0
    
    for server_id in get_all_server_ids():
        config = load_server_config(server_id)
        for calendar in config.get("calendars", []):
            # Skip calendars without user_id instead of crashing
            if "user_id" not in calendar:
                missing_user_id_count += 1
                logger.warning(f"Calendar in server {server_id} missing user_id field: {calendar.get('name', 'Unnamed')}, ID: {calendar.get('id', 'Unknown')}")
                calendar["user_id"] = str(server_id)  # Fallback to server_id
                save_server_config(server_id, config)
            
            user_id = calendar["user_id"]
            if user_id not in GROUPED_CALENDARS:
                GROUPED_CALENDARS[user_id] = []
            GROUPED_CALENDARS[user_id].append({
                "server_id": server_id,
                "type": calendar["type"],
                "id": calendar["id"],
                "name": calendar.get("name", "Unnamed Calendar"),
                "user_id": user_id  # Make sure this is included in the meta
            })

    calendar_count = sum(len(calendars) for calendars in GROUPED_CALENDARS.values())
    logger.info(f"Loaded {len(GROUPED_CALENDARS)} user-specific calendars ({calendar_count} total calendars) from server configurations.")
    if missing_user_id_count > 0:
        logger.warning(f"Fixed {missing_user_id_count} calendars with missing user_id field.")

# Register the calendar reload function now that it's defined
register_calendar_reload_callback(load_calendars_from_server_configs)

# Remaining functions from events.py stay the same, but we'll change the old 
# parse_calendar_sources and get_user_tag_mapping functions to be deprecated

# ╔════════════════════════════════════════════════════════════════════╗
# ║ 🔁 retry_api_call                                                  ║
# ║ Helper to retry Google API calls with exponential backoff         ║
# ╚════════════════════════════════════════════════════════════════════╝
def retry_api_call(func, *args, max_retries=3, **kwargs):
    """
    Retry a Google API call with exponential backoff on transient errors
    and token bucket rate limiting to prevent quota exhaustion.
    
    Args:
        func: The API function to call
        max_retries: Maximum number of retry attempts
        *args, **kwargs: Arguments to pass to the function
        
    Returns:
        The result of the API call or None if all retries failed
    """
    global _api_last_error_time, _api_error_count
    
    # Import rate limiters
    from utils.rate_limiter import CALENDAR_API_LIMITER, EVENT_LIST_LIMITER
    
    # Determine which rate limiter to use based on function signature
    # Default to the general Calendar API limiter
    rate_limiter = CALENDAR_API_LIMITER
    
    # Use more specific limiter for list operations (which can be expensive)
    func_str = str(func)
    if 'list(' in func_str.lower() or 'events()' in func_str:
        rate_limiter = EVENT_LIST_LIMITER
        logger.debug("Using event list rate limiter for API call")
    
    # Check if we've had too many errors recently
    if _api_last_error_time and _api_error_count >= _MAX_API_ERRORS:
        # Check if enough time has passed to reset the counter
        if datetime.now() - _api_last_error_time > _API_BACKOFF_RESET:
            logger.info("API error count reset after backoff period")
            _api_error_count = 0
        else:
            logger.warning(f"Too many API errors ({_api_error_count}), backing off")
            return None
    
    # Acquire a token from the rate limiter (this will wait if necessary)
    if not rate_limiter.consume(tokens=1, wait=True):
        logger.error("Failed to acquire rate limit token - this should not happen with wait=True")
        return None
    
    last_exception = None
    
    for attempt in range(max_retries):
        try:
            return func(*args, **kwargs)
            
        except HttpError as e:
            status_code = e.resp.status
            
            # For rate limit errors, wait longer and retry with higher backoff
            if (status_code == 429):
                backoff = (5 ** attempt) + random.uniform(1, 3)  # More aggressive backoff
                logger.warning(f"Rate limit hit ({status_code}), attempt {attempt+1}/{max_retries}, backing off for {backoff:.2f}s: {str(e)}")
                time.sleep(backoff)
                last_exception = e
                continue
            
            # Don't retry on other client errors
            if status_code < 500 and status_code != 429:
                logger.warning(f"Non-retryable Google API error: {status_code} - {str(e)}")
                _api_error_count += 1
                _api_last_error_time = datetime.now()
                raise
                
            # For server errors, use standard backoff
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
    """DEPRECATED: Use load_calendars_from_server_configs() instead."""
    logger.warning("load_calendar_sources() is deprecated. Use load_calendars_from_server_configs() instead.")
    load_calendars_from_server_configs()
    return GROUPED_CALENDARS

# ╔════════════════════════════════════════════════════════════════════╗
# ║ 💾 Event Snapshot Persistence                                      ║
# ╚════════════════════════════════════════════════════════════════════╝
def load_previous_events(server_id: int):
    try:
        path = get_events_file(server_id)
        if (os.path.exists(path)):
            with open(path, "r", encoding="utf-8") as f:
                logger.debug("Loaded previous event snapshot from disk.")
                return json.load(f)
    except json.JSONDecodeError:
        logger.warning("Previous events file corrupted. Starting fresh.")
    except Exception as e:
        logger.exception(f"Error loading previous events: {e}")
    return {}

def save_current_events_for_key(server_id: int, key, events):
    try:
        logger.debug(f"Saving {len(events)} events under key: {key}")
        all_data = load_previous_events(server_id)
        all_data[key] = events
        events_file_path = get_events_file(server_id)
        with open(events_file_path, "w", encoding="utf-8") as f:
            json.dump(all_data, f, ensure_ascii=False, indent=4)
        logger.info(f"Saved events for key '{key}' to {events_file_path}.")
    except Exception as e:
        logger.exception(f"Error saving events for key {key}: {e}")

def load_post_tracking(server_id: int) -> dict:
    """
    Load tracking data for daily posts from a file.

    Args:
        server_id: The ID of the server to load tracking data for.

    Returns:
        A dictionary containing tracking data, or an empty dictionary if no data exists.
    """
    try:
        path = get_events_file(server_id)
        if os.path.exists(path):
            with open(path, "r", "utf-8") as f:
                data = json.load(f)
                return data.get("daily_posts", {})
    except json.JSONDecodeError:
        logger.warning(f"Tracking file for server {server_id} is corrupted. Starting fresh.")
    except Exception as e:
        logger.exception(f"Error loading post tracking for server {server_id}: {e}")
    return {}

# ╔════════════════════════════════════════════════════════════════════╗
# ║ 📆 Event Fetching                                                  ║
# ║ Retrieves events from Google or ICS sources                        ║
# ╚════════════════════════════════════════════════════════════════════╝
def get_google_events(start_date, end_date, calendar_id):
    """
    Fetch events from a Google Calendar within a specified date range.
    
    Args:
        start_date: The start date of the range to fetch events for
        end_date: The end date of the range to fetch events for  
        calendar_id: The Google Calendar ID to fetch from
        
    Returns:
        A list of events in Google Calendar API format
    """
    try:
        # Ensure we have a valid service connection
        if not service:
            logger.error(f"Google Calendar service not initialized, can't fetch events for {calendar_id}")
            return []
            
        # Format date ranges in UTC format as required by Google Calendar API
        start_utc = start_date.isoformat() + "T00:00:00Z"  # Start at beginning of day in UTC
        end_utc = end_date.isoformat() + "T23:59:59Z"      # End at end of day in UTC
        
        logger.debug(f"Fetching Google events for calendar {calendar_id} from {start_utc} to {end_utc}")
        
        # Use retry_api_call to handle transient errors
        result = retry_api_call(
            lambda: service.events().list(
                calendarId=calendar_id,
                timeMin=start_utc,
                timeMax=end_utc,
                singleEvents=True,  # Expand recurring events into single instances
                orderBy="startTime",
                maxResults=2500     # Reasonable upper limit
            ).execute()
        )
        
        if result is None:
            logger.warning(f"Failed to fetch events for Google Calendar {calendar_id} after retries")
            return []
            
        items = result.get("items", [])
        
        # Add source field to all events for better tracking
        for item in items:
            item["source"] = "google"
            
        # Process events before returning
        logger.debug(f"Successfully fetched {len(items)} events from Google Calendar {calendar_id}")
        return items
    except HttpError as e:
        status_code = e.resp.status
        if status_code == 404:
            logger.error(f"Calendar not found or not shared with service account: {calendar_id}")
        elif status_code == 403:
            logger.error(f"Permission denied to access calendar {calendar_id}. Ensure the calendar is shared with the service account.")
        else:
            logger.exception(f"Google API error ({status_code}) fetching events from {calendar_id}: {e}")
        return []
    except Exception as e:
        logger.exception(f"Error fetching Google events from calendar {calendar_id}: {e}")
        return []

def get_ics_events(start_date, end_date, url):
    """
    Retrieve events from an ICS calendar URL within a specified date range.
    
    Args:
        start_date: The start date of the range to fetch events for
        end_date: The end date of the range to fetch events for
        url: The URL of the ICS calendar file
        
    Returns:
        A list of events in a standardized format matching Google Calendar API format
    """
    try:
        logger.debug(f"Fetching ICS events from {url}")
        
        # Fetch ICS content with timeout and proper error handling
        response = requests.get(url, timeout=10)
        response.raise_for_status()  # Raise exception for HTTP errors
        response.encoding = 'utf-8'
        
        # Parse the calendar
        cal = ICS_Calendar(response.text)
        
        if not hasattr(cal, 'events'):
            logger.warning(f"No events found in ICS calendar: {url}")
            return []
            
        logger.debug(f"Parsing {len(cal.events)} events from ICS calendar")
        events = []
        
        # Parse each event in the calendar
        for e in cal.events:
            try:
                # Skip events outside our date range (use date component for comparison)
                event_date = e.begin.date()
                if not (start_date <= event_date <= end_date):
                    continue
                
                # Generate a stable ID for the event based on its core properties
                id_source = f"{e.name}|{e.begin}|{e.end}|{e.location or ''}"
                event_id = hashlib.md5(id_source.encode("utf-8")).hexdigest()
                
                # Convert to standard format (compatible with Google Calendar API format)
                event = {
                    "id": event_id,
                    "summary": e.name or "Unnamed Event",
                    "start": {"dateTime": e.begin.isoformat()},
                    "end": {"dateTime": e.end.isoformat()},
                    "location": e.location or "",
                    "description": e.description or "",
                    "source": "ics",
                    # Add other fields that might be useful
                    "status": "confirmed"
                }
                
                # Handle all-day events (no time component)
                if e.all_day:
                    event["start"] = {"date": e.begin.date().isoformat()}
                    event["end"] = {"date": e.end.date().isoformat()}
                
                events.append(event)
            except Exception as inner_e:
                # Catch errors for individual events but continue processing others
                logger.warning(f"Error processing individual ICS event: {inner_e}")
                continue

        # De-duplicate events using the fingerprint
        seen_fps = set()
        deduped = []
        for e in events:
            fp = compute_event_fingerprint(e)
            if fp and fp not in seen_fps:
                seen_fps.add(fp)
                deduped.append(e)
                
        if len(deduped) < len(events):
            logger.info(f"Removed {len(events) - len(deduped)} duplicate events from ICS calendar")
            
        logger.debug(f"Successfully processed {len(deduped)} unique ICS events from {url}")
        return deduped
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Network error fetching ICS calendar {url}: {str(e)}")
        return []
    except Exception as e:
        logger.exception(f"Error parsing ICS calendar {url}: {e}")
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
    the specified date range with caching for improved performance.

    Args:
        source_meta: A dictionary describing the calendar source,
            e.g. { "type": "google", "id": <calendar ID>, ... }.
        start_date: The start date of the requested range.
        end_date: The end date of the requested range.

    Returns:
        A list of event dictionaries from this source in a unified format.
    """
    # Capture basic metadata for logging and troubleshooting
    calendar_name = source_meta.get('name', 'Unknown Calendar')
    calendar_type = source_meta.get('type', 'unknown')
    calendar_id = source_meta.get('id', 'unknown-id')
    
    # Input validation
    if not isinstance(start_date, date) or not isinstance(end_date, date):
        logger.error(f"Invalid date parameters for calendar {calendar_name}")
        return []
    
    if start_date > end_date:
        logger.error(f"Start date {start_date} is after end date {end_date} for calendar {calendar_name}")
        return []
    
    # Create a unique cache key for this request
    cache_key = f"{calendar_id}_{calendar_type}_{start_date.isoformat()}_{end_date.isoformat()}"
    
    # Import the cache module only when needed to avoid circular imports
    def get_cached_events(key):
        from utils.cache import event_cache
        return event_cache.get(key)
    
    def set_cached_events(key, value):
        from utils.cache import event_cache
        event_cache.set(key, value)
    
    # Try to get from cache first
    cached_events = get_cached_events(cache_key)
    if cached_events is not None:
        logger.debug(f"Cache hit for {calendar_name} events ({start_date} to {end_date})")
        return cached_events
    
    # Not in cache, need to fetch from source
    logger.debug(f"Cache miss for {calendar_name} events, fetching from {calendar_type} source")
    
    # Implement calendar-specific fetching with enhanced error handling
    try:
        events = []
        if (calendar_type == "google"):
            events = get_google_events(start_date, end_date, calendar_id)
        elif (calendar_type == "ics"):
            events = get_ics_events(start_date, end_date, calendar_id)
        else:
            logger.warning(f"Unsupported calendar type: {calendar_type}")
            return []
        
        # Always sort events for consistent processing
        if events:
            events.sort(key=lambda e: e["start"].get("dateTime", e["start"].get("date", "")))
            logger.info(f"Successfully fetched {len(events)} events from {calendar_name} ({calendar_type})")
        else:
            logger.info(f"No events found for {calendar_name} in range {start_date} to {end_date}")
        
        # Cache the result before returning
        result = events or []
        set_cached_events(cache_key, result)
        return result
        
    except Exception as e:
        logger.exception(f"Error fetching events from {calendar_name} ({calendar_type}): {e}")
        return []

# ╔════════════════════════════════════════════════════════════════════╗
# ║ 🧬 compute_event_fingerprint                                       ║
# ║ Generates a stable hash for an event's core details               ║
# ╚════════════════════════════════════════════════════════════════════╝
def compute_event_fingerprint(event: dict) -> str:
    """
    Generates a stable hash for an event's core details to track changes.
    
    Args:
        event: Dictionary containing event data from Google Calendar or ICS
        
    Returns:
        A consistent MD5 hash string that identifies this event's core properties
        
    This function normalizes dates, times, and text to ensure consistent 
    fingerprinting even when minor formatting differences exist.
    """
    if not event or not isinstance(event, dict):
        logger.error("Invalid event data for fingerprinting")
        return ""
    
    try:
        def normalize_time(val: str) -> str:
            """Normalize datetime strings to a consistent format."""
            if not val:
                return ""
            
            # Handle Z timezone marker
            if "Z" in val:
                val = val.replace("Z", "+00:00")
                
            # For date-only format (no time component)
            if "T" not in val:
                return val  # Return as-is for date-only format
                
            try:
                dt = datetime.fromisoformat(val)
                return dt.isoformat(timespec="minutes")
            except (ValueError, TypeError):
                logger.warning(f"Could not parse datetime: {val}")
                return val

        def clean(text: str) -> str:
            """Normalize text by cleaning whitespace and ensuring it's a string."""
            if not text:
                return ""
            if not isinstance(text, str):
                return str(text)
            return " ".join(text.strip().split())

        # Extract and normalize core event properties
        summary = clean(event.get("summary", ""))
        location = clean(event.get("location", ""))
        description = clean(event.get("description", ""))
        
        # Handle potentially missing start/end structures
        start_container = event.get("start", {})
        end_container = event.get("end", {})
        
        if not isinstance(start_container, dict):
            start_container = {"date": str(start_container)}
        if not isinstance(end_container, dict):
            end_container = {"date": str(end_container)}
            
        # Get raw datetime values
        start_raw = start_container.get("dateTime", start_container.get("date", ""))
        end_raw = end_container.get("dateTime", end_container.get("date", ""))
        
        # Normalize times
        start = normalize_time(start_raw)
        end = normalize_time(end_raw)

        # Create minimal normalized representation
        trimmed = {
            "summary": summary,
            "start": start,
            "end": end,
            "location": location,
            "description": description
        }

        # Generate stable hash from sorted JSON
        normalized_json = json.dumps(trimmed, sort_keys=True)
        return hashlib.md5(normalized_json.encode("utf-8")).hexdigest()
    except Exception as e:
        event_id = event.get("id", "unknown")
        event_summary = event.get("summary", "untitled")
        logger.exception(f"Error computing fingerprint for event '{event_summary}' (ID: {event_id}): {e}")
        
        # Fallback fingerprinting using just id and summary when full method fails
        fallback_str = f"{event.get('id', '')}|{event.get('summary', '')}"
        return hashlib.md5(fallback_str.encode("utf-8")).hexdigest()

# ╔════════════════════════════════════════════════════════════════════╗
# ║ 🔄 Reload Functions                                                ║
# ║ Functions to handle reloading after setup changes                  ║
# ╚════════════════════════════════════════════════════════════════════╝
reinitialize_lock = Lock()

async def reinitialize_events():
    """Reinitialize events with concurrency control."""
    async with reinitialize_lock:
        if reinitialize_lock.locked():
            logger.warning("Reinitialize events is already in progress. Skipping duplicate call.")
            return False

        logger.info("Starting reinitialization of events.")
        # Import at function level to avoid circular imports
        from bot.tasks import initialize_event_snapshots
        from config.server_config import get_all_server_ids, load_server_config

        # First, reload calendar configurations for all servers
        logger.info("Reloading calendar configurations for all servers")
        for server_id in get_all_server_ids():
            config = load_server_config(server_id)
            logger.debug(f"Loaded config for server {server_id}: {config}")

        # Then initialize event snapshots
        logger.info("Re-initializing event snapshots after configuration change")
        await initialize_event_snapshots()

        logger.info("Reinitialization of events completed.")
        return True

# Initialize calendars on module load
load_calendars_from_server_configs()
