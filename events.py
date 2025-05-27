import os
import json
import hashlib
import requests
import time
import random
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional, Any
from ics import Calendar as ICS_Calendar
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from environ import GOOGLE_APPLICATION_CREDENTIALS, CALENDAR_SOURCES, USER_TAG_MAPPING
from log import logger
from ai_title_parser import simplify_event_title

# ╔════════════════════════════════════════════════════════════════════╗
# ║ 🔐 Google Calendar API Initialization                             ║
# ║ Sets up credentials and API client for accessing Google Calendar ║
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
    service = None  # Will trigger fallback behavior in functions

# ╔════════════════════════════════════════════════════════════════════╗
# ║ 👥 Tag Mapping (User ID → Tag)                                     ║
# ╚════════════════════════════════════════════════════════════════════╝
def get_user_tag_mapping() -> Dict[int, str]:
    """Parse USER_TAG_MAPPING into a dictionary of user IDs to tags with robust error handling."""
    try:
        mapping = {}
        
        # Handle None or empty case
        if not USER_TAG_MAPPING:
            logger.warning("USER_TAG_MAPPING is empty or not set")
            return {}
            
        entries = [entry.strip() for entry in USER_TAG_MAPPING.split(",") if entry.strip()]
        
        if not entries:
            logger.warning("No valid entries found in USER_TAG_MAPPING")
            return {}
            
        for entry in entries:
            try:
                if ":" not in entry:
                    logger.warning(f"Skipping invalid tag mapping (missing colon): '{entry}'")
                    continue
                    
                parts = entry.split(":", 1)
                if len(parts) != 2:
                    logger.warning(f"Skipping invalid tag mapping format: '{entry}'")
                    continue
                    
                user_id_str, tag = parts
                
                # Validate user_id is numeric
                if not user_id_str.strip().isdigit():
                    logger.warning(f"Invalid user ID (non-numeric) in USER_TAG_MAPPING: '{entry}'")
                    continue
                    
                user_id = int(user_id_str.strip())
                tag = tag.strip().upper()
                
                # Validate tag is not empty
                if not tag:
                    logger.warning(f"Empty tag for user ID {user_id}, skipping")
                    continue
                    
                mapping[user_id] = tag
                logger.debug(f"Mapped user {user_id} to tag {tag}")
                
            except ValueError:
                logger.warning(f"Invalid user ID format in USER_TAG_MAPPING: '{entry}'")
            except Exception as e:
                logger.warning(f"Error processing tag mapping entry '{entry}': {e}")
                
        if not mapping:
            logger.warning("No valid user-tag mappings found")
            
        return mapping
    except Exception as e:
        logger.exception(f"Error in get_user_tag_mapping: {e}")
        return {}

USER_TAG_MAP = get_user_tag_mapping()

# Populated during bot startup
TAG_NAMES = {}
TAG_COLORS = {}

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

# ╔════════════════════════════════════════════════════════════════════╗
# ║ 📦 Calendar Source Parsing                                         ║
# ║ Parses CALENDAR_SOURCES into structured source info               ║
# ╚════════════════════════════════════════════════════════════════════╝
def parse_calendar_sources() -> List[Tuple[str, str, str]]:
    """Parse CALENDAR_SOURCES with robust validation and error handling."""
    parsed = []
    
    # Handle empty/None case
    if not CALENDAR_SOURCES:
        logger.warning("CALENDAR_SOURCES is empty or not set")
        return []
    
    entries = [entry.strip() for entry in CALENDAR_SOURCES.split(",") if entry.strip()]
    
    if not entries:
        logger.warning("No valid entries found in CALENDAR_SOURCES")
        return []
        
    for entry in entries:
        try:
            # Check for valid prefix
            if not (entry.startswith("google:") or entry.startswith("ics:")):
                logger.warning(f"Skipping invalid calendar source (unknown type): '{entry}'")
                continue
                
            prefix, rest = entry.split(":", 1)
            
            # Check for valid format (needs second colon for tag)
            if ":" not in rest:
                logger.warning(f"Skipping invalid calendar source (missing tag): '{entry}'")
                continue
                
            id_or_url, tag = rest.rsplit(":", 1)
            id_or_url = id_or_url.strip()
            tag = tag.strip().upper()
            
            # Validate parts aren't empty
            if not id_or_url:
                logger.warning(f"Empty calendar ID/URL in source: '{entry}'")
                continue
                
            if not tag:
                logger.warning(f"Empty tag for calendar {id_or_url}, using 'MISC' instead")
                tag = "MISC"
                
            # Additional URL validation for ICS sources
            if prefix == "ics":
                if not (id_or_url.startswith("http://") or id_or_url.startswith("https://")):
                    logger.warning(f"Invalid ICS URL format: '{id_or_url}', skipping")
                    continue
                    
            parsed.append((prefix, id_or_url, tag))
            logger.debug(f"Parsed calendar source: {prefix}:{id_or_url} (tag={tag})")
                
        except Exception as e:
            logger.warning(f"Error parsing calendar source '{entry}': {e}")
            
    if not parsed:
        logger.warning("No valid calendar sources found")
        
    return parsed

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
# ║ 📄 Calendar Metadata Fetching                                     ║
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
# ║ 📚 Source Loader                                                   ║
# ║ Groups calendar sources by tag and loads them into memory         ║
# ╚════════════════════════════════════════════════════════════════════╝
def load_calendar_sources():
    try:
        logger.info("Loading calendar sources...")
        grouped = {}
        for ctype, cid, tag in parse_calendar_sources():
            try:
                meta = fetch_google_calendar_metadata(cid) if ctype == "google" else fetch_ics_calendar_metadata(cid)
                meta["tag"] = tag
                grouped.setdefault(tag, []).append(meta)
                logger.debug(f"Calendar loaded: {meta}")
            except Exception as e:
                logger.exception(f"Error loading calendar source {cid} for tag {tag}: {e}")
        return grouped
    except Exception as e:
        logger.exception(f"Error in load_calendar_sources: {e}")
        return {}

GROUPED_CALENDARS = load_calendar_sources()

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
        items = result.get("items", [])
        
        # Process events to simplify titles
        for event in items:
            original_title = event.get("summary", "")
            if original_title:
                simplified_title = simplify_event_title(original_title)
                event["original_summary"] = original_title  # Preserve original
                event["summary"] = simplified_title
                logger.debug(f"Title simplified: '{original_title}' -> '{simplified_title}'")
        
        logger.debug(f"Fetched {len(items)} Google events for {calendar_id}")
        return items
    except Exception as e:
        logger.exception(f"Error fetching Google events from calendar {calendar_id}: {e}")
        return []

def get_ics_events(start_date, end_date, url):
    try:
        logger.debug(f"Fetching ICS events from {url}")
        response = requests.get(url, timeout=10)
        response.encoding = 'utf-8'
        
        # Basic validation of ICS content before attempting to parse
        content = response.text
        if not content or len(content) < 50:  # Minimal valid ICS would be larger
            logger.warning(f"ICS content too small or empty from {url}")
            return []
            
        if not content.startswith("BEGIN:VCALENDAR") or "END:VCALENDAR" not in content:
            logger.warning(f"Invalid ICS format (missing BEGIN/END markers) from {url}")
            return []
        
        # Safely parse the ICS calendar with error handling for specific parser issues    
        try:
            cal = ICS_Calendar(content)
        except IndexError as ie:
            # Handle the specific TatSu parser error we're seeing
            logger.warning(f"Parser index error in ICS file from {url}: {ie}")
            return []
        except Exception as parser_error:
            logger.warning(f"ICS parser error for {url}: {parser_error}")
            return []
            
        events = []
        for e in cal.events:
            if start_date <= e.begin.date() <= end_date:
                id_source = f"{e.name}|{e.begin}|{e.end}|{e.location or ''}"
                original_title = e.name or ""
                simplified_title = simplify_event_title(original_title) if original_title else "Event"
                
                event = {
                    "summary": simplified_title,
                    "original_summary": original_title,  # Preserve original
                    "start": {"dateTime": e.begin.isoformat()},
                    "end": {"dateTime": e.end.isoformat()},
                    "location": e.location or "",
                    "description": e.description or "",
                    "id": hashlib.md5(id_source.encode("utf-8")).hexdigest()
                }
                events.append(event)
                logger.debug(f"ICS title simplified: '{original_title}' -> '{simplified_title}'")

        seen_fps = set()
        deduped = []
        for e in events:
            fp = compute_event_fingerprint(e)
            if fp not in seen_fps:
                seen_fps.add(fp)
                deduped.append(e)
        logger.debug(f"Deduplicated to {len(deduped)} ICS events")
        return deduped
    except requests.exceptions.RequestException as e:
        logger.exception(f"Error fetching ICS calendar: {url}")
        return []
    except Exception as e:
        logger.exception(f"Error fetching/parsing ICS calendar: {url}")
        return []

def get_events(source_meta, start_date, end_date):
    logger.debug(f"Getting events from source: {source_meta['name']} ({source_meta['type']})")
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
