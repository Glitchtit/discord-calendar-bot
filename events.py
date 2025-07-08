import os
import json
import hashlib
import requests
import time
import random
import ssl
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional, Any
from ics import Calendar as ICS_Calendar # type: ignore
from google.oauth2 import service_account # type: ignore
from googleapiclient.discovery import build # type: ignore
from googleapiclient.errors import HttpError # type: ignore
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
            
        except ssl.SSLError as e:
            # SSL errors are retryable as they're often temporary network issues
            backoff = (2 ** attempt) + random.uniform(0, 1)
            logger.warning(f"SSL error in API call, attempt {attempt+1}/{max_retries}, backing off for {backoff:.2f}s: {str(e)}")
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
    """Fetch events from Google Calendar with robust error handling and retry logic."""
    if not service:
        logger.error(f"Google Calendar service not initialized, cannot fetch events for {calendar_id}")
        return []
    
    try:
        start_utc = start_date.isoformat() + "T00:00:00Z"
        end_utc = end_date.isoformat() + "T23:59:59Z"
        logger.debug(f"Fetching Google events for calendar {calendar_id} from {start_utc} to {end_utc}")
        
        # Use retry_api_call to handle transient errors
        def api_call():
            return service.events().list(
                calendarId=calendar_id,
                timeMin=start_utc,
                timeMax=end_utc,
                singleEvents=True,
                orderBy="startTime"
            ).execute()
        
        result = retry_api_call(api_call, max_retries=3)
        
        if result is None:
            logger.warning(f"Failed to fetch events for calendar {calendar_id} after retries")
            return []
            
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
        
    except ssl.SSLError as e:
        logger.error(f"SSL error fetching Google events from calendar {calendar_id}: {e}")
        logger.info("This may be a temporary network issue. The calendar will be retried on the next sync.")
        return []
    except requests.exceptions.ConnectionError as e:
        logger.error(f"Connection error fetching Google events from calendar {calendar_id}: {e}")
        logger.info("Network connection issue. The calendar will be retried on the next sync.")
        return []
    except requests.exceptions.Timeout as e:
        logger.error(f"Timeout error fetching Google events from calendar {calendar_id}: {e}")
        logger.info("Request timed out. The calendar will be retried on the next sync.")
        return []
    except HttpError as e:
        if e.resp.status in [403, 404]:
            logger.error(f"Access denied or calendar not found for {calendar_id}: {e}")
            logger.info("Check calendar permissions and ID validity.")
        else:
            logger.error(f"Google API error fetching events from calendar {calendar_id}: {e}")
        return []
    except Exception as e:
        logger.exception(f"Unexpected error fetching Google events from calendar {calendar_id}: {e}")
        return []

def get_ics_events(start_date, end_date, url):
    """Fetch events from ICS calendar with robust error handling."""
    try:
        logger.debug(f"Fetching ICS events from {url}")
        response = requests.get(url, timeout=10)
        response.encoding = 'utf-8'
        response.raise_for_status()  # Raise an exception for bad status codes
        
        # Basic validation of ICS content before attempting to parse
        content = response.text
        if not content or len(content) < 50:  # Minimal valid ICS would be larger
            logger.warning(f"ICS content too small or empty from {url}")
            return []
            
        # Additional content validation
        if len(content) > 50_000_000:  # 50MB limit to prevent memory issues
            logger.warning(f"ICS content too large (>{len(content)/1_000_000:.1f}MB) from {url}")
            return []
            
        if not content.startswith("BEGIN:VCALENDAR") or "END:VCALENDAR" not in content:
            logger.warning(f"Invalid ICS format (missing BEGIN/END markers) from {url}")
            return []
            
        # Check for potential malicious content patterns
        suspicious_patterns = [
            b'\x00',  # Null bytes
            '\x00',   # Null bytes in text
        ]
        
        content_bytes = content.encode('utf-8', errors='ignore')
        for pattern in suspicious_patterns:
            if isinstance(pattern, bytes) and pattern in content_bytes:
                logger.warning(f"Suspicious content detected in ICS from {url}")
                return []
            elif isinstance(pattern, str) and pattern in content:
                logger.warning(f"Suspicious content detected in ICS from {url}")
                return []
        
        # Safely parse the ICS calendar with comprehensive error handling for parser issues    
        try:
            cal = ICS_Calendar(content)
        except IndexError as ie:
            # Handle the specific TatSu parser error we're seeing (pop from empty list)
            logger.warning(f"Parser index error in ICS file from {url}: {ie}")
            return []
        except ValueError as ve:
            # Handle malformed datetime or other value parsing errors
            logger.warning(f"ICS value parsing error for {url}: {ve}")
            return []
        except TypeError as te:
            # Handle 'NoneType' object is not iterable and similar type errors
            logger.warning(f"ICS type error for {url}: {te}")
            return []
        except AttributeError as ae:
            # Handle missing attribute errors during parsing
            logger.warning(f"ICS attribute error for {url}: {ae}")
            return []
        except ImportError as ime:
            # Handle missing dependencies or module issues
            logger.warning(f"ICS import error for {url}: {ime}")
            return []
        except MemoryError as me:
            # Handle cases where ICS file is too large
            logger.warning(f"ICS memory error for {url}: File too large to process")
            return []
        except RecursionError as re:
            # Handle infinite recursion in malformed ICS files
            logger.warning(f"ICS recursion error for {url}: Malformed file structure")
            return []
        except UnicodeDecodeError as ude:
            # Handle encoding issues
            logger.warning(f"ICS encoding error for {url}: {ude}")
            return []
        except KeyboardInterrupt:
            # Allow clean shutdown
            logger.info("ICS parsing interrupted by user")
            raise
        except Exception as parser_error:
            # Catch any other parsing errors including TatSu parser exceptions
            error_msg = str(parser_error)
            if "ALPHADIGIT_MINUS_PLUS" in error_msg or "contentline" in error_msg:
                logger.warning(f"ICS datetime format error for {url}: Malformed DTSTART/DTEND field")
            elif "pop from empty list" in error_msg:
                logger.warning(f"Parser index error in ICS file from {url}: {parser_error}")
            elif "'NoneType' object is not iterable" in error_msg:
                logger.warning(f"ICS parser error for {url}: {parser_error}")
            else:
                logger.warning(f"ICS parser error for {url}: {parser_error}")
            return []
            
        # Safely iterate through events with additional error handling
        events = []
        if not hasattr(cal, 'events') or cal.events is None:
            logger.warning(f"No events found in ICS calendar from {url}")
            return []
            
        try:
            # Convert to list first to avoid iterator issues
            cal_events = list(cal.events) if hasattr(cal.events, '__iter__') else []
        except (TypeError, ValueError, AttributeError) as e:
            logger.warning(f"Error accessing events from ICS calendar {url}: {e}")
            return []
            
        try:
            for i, e in enumerate(cal_events):
                try:
                    # Add safety check for maximum number of events to prevent memory issues
                    if i >= 1000:  # Limit to 1000 events per calendar
                        logger.warning(f"ICS calendar {url} has too many events (>1000), truncating")
                        break
                        
                    # Validate event has required fields
                    if not hasattr(e, 'begin') or not hasattr(e, 'end') or e.begin is None or e.end is None:
                        logger.debug(f"Skipping event with missing start/end time from {url}")
                        continue
                        
                    # Additional safety checks for event properties
                    try:
                        # Test if we can access the date property safely
                        event_date = e.begin.date()
                        event_end_date = e.end.date()
                    except (AttributeError, ValueError, TypeError) as date_error:
                        logger.debug(f"Skipping event with invalid date from {url}: {date_error}")
                        continue
                        
                    # Check if event is in date range
                    if not (start_date <= event_date <= end_date):
                        continue
                        
                    # Safely extract event data with additional error handling
                    try:
                        original_title = getattr(e, 'name', None) or getattr(e, 'summary', None) or ""
                        location = getattr(e, 'location', None) or ""
                        description = getattr(e, 'description', None) or ""
                        
                        # Ensure string types and handle encoding issues
                        if original_title and not isinstance(original_title, str):
                            original_title = str(original_title)
                        if location and not isinstance(location, str):
                            location = str(location)
                        if description and not isinstance(description, str):
                            description = str(description)
                            
                        # Truncate very long fields to prevent memory issues
                        original_title = original_title[:500] if original_title else ""
                        location = location[:200] if location else ""
                        description = description[:1000] if description else ""
                        
                    except (UnicodeDecodeError, UnicodeEncodeError) as encoding_error:
                        logger.debug(f"Encoding error processing event from {url}: {encoding_error}")
                        original_title = "Event"
                        location = ""
                        description = ""
                    except Exception as field_error:
                        logger.debug(f"Error extracting event fields from {url}: {field_error}")
                        original_title = "Event"
                        location = ""
                        description = ""
                        
                    # Create unique ID for event
                    id_source = f"{original_title}|{e.begin}|{e.end}|{location}"
                    
                    # Safely generate simplified title
                    try:
                        simplified_title = simplify_event_title(original_title) if original_title else "Event"
                    except Exception as title_error:
                        logger.debug(f"Error simplifying title '{original_title}' from {url}: {title_error}")
                        simplified_title = original_title or "Event"
                    
                    try:
                        event = {
                            "summary": simplified_title,
                            "original_summary": original_title,  # Preserve original
                            "start": {"dateTime": e.begin.isoformat()},
                            "end": {"dateTime": e.end.isoformat()},
                            "location": location,
                            "description": description,
                            "id": hashlib.md5(id_source.encode("utf-8")).hexdigest()
                        }
                        events.append(event)
                        logger.debug(f"ICS title simplified: '{original_title}' -> '{simplified_title}'")
                    except Exception as event_creation_error:
                        logger.warning(f"Error creating event object from {url}: {event_creation_error}")
                        continue
                    
                except KeyboardInterrupt:
                    # Allow clean shutdown
                    logger.info("Event processing interrupted by user")
                    raise
                except Exception as event_error:
                    # Log individual event processing errors but continue with other events
                    logger.warning(f"Error processing individual event from {url}: {event_error}")
                    continue
                    
        except KeyboardInterrupt:
            # Allow clean shutdown
            logger.info("Event iteration interrupted by user")
            raise
        except Exception as iteration_error:
            logger.warning(f"Error iterating through events from {url}: {iteration_error}")
            return []

        # Deduplicate events with error handling
        seen_fps = set()
        deduped = []
        for e in events:
            try:
                fp = compute_event_fingerprint(e)
                if fp and fp not in seen_fps:
                    seen_fps.add(fp)
                    deduped.append(e)
                elif not fp:
                    # If fingerprinting fails, include the event anyway but log it
                    logger.debug(f"Could not fingerprint event, including anyway: {e.get('summary', 'Unknown')}")
                    deduped.append(e)
            except Exception as fp_error:
                logger.warning(f"Error computing fingerprint for event from {url}: {fp_error}")
                # Include the event anyway to avoid losing data
                deduped.append(e)
                continue
                
        logger.debug(f"Deduplicated to {len(deduped)} ICS events from {url}")
        return deduped
        
    except ssl.SSLError as e:
        logger.error(f"SSL error fetching ICS calendar {url}: {e}")
        logger.info("This may be a temporary network issue. The calendar will be retried on the next sync.")
        return []
    except requests.exceptions.ConnectionError as e:
        logger.error(f"Connection error fetching ICS calendar {url}: {e}")
        logger.info("Network connection issue. The calendar will be retried on the next sync.")
        return []
    except requests.exceptions.Timeout as e:
        logger.error(f"Timeout error fetching ICS calendar {url}: {e}")
        logger.info("Request timed out. The calendar will be retried on the next sync.")
        return []
    except requests.exceptions.HTTPError as e:
        logger.error(f"HTTP error fetching ICS calendar {url}: {e}")
        if e.response.status_code in [403, 404]:
            logger.info("Check calendar URL validity and permissions.")
        else:
            logger.info("The calendar will be retried on the next sync.")
        return []
    except requests.exceptions.RequestException as e:
        logger.error(f"Network error fetching ICS calendar {url}: {e}")
        logger.info("The calendar will be retried on the next sync.")
        return []
    except Exception as e:
        logger.exception(f"Unexpected error fetching/parsing ICS calendar {url}: {e}")
        logger.info("The calendar will be retried on the next sync.")
        return []

def get_events(source_meta, start_date, end_date):
    """Fetch events from a calendar source with comprehensive error handling."""
    try:
        logger.debug(f"Getting events from source: {source_meta['name']} ({source_meta['type']})")
        
        # Validate source metadata
        if not isinstance(source_meta, dict):
            logger.error(f"Invalid source metadata: {source_meta}")
            return []
            
        source_type = source_meta.get("type")
        source_id = source_meta.get("id")
        source_name = source_meta.get("name", "Unknown")
        
        if not source_type or not source_id:
            logger.error(f"Missing required fields in source metadata: {source_meta}")
            return []
        
        # Route to appropriate fetcher based on source type
        if source_type == "google":
            return get_google_events(start_date, end_date, source_id)
        elif source_type == "ics":
            return get_ics_events(start_date, end_date, source_id)
        else:
            logger.warning(f"Unknown calendar source type '{source_type}' for source '{source_name}'")
            return []
            
    except Exception as e:
        source_name = source_meta.get("name", "Unknown") if isinstance(source_meta, dict) else "Unknown"
        logger.exception(f"Unexpected error getting events from source '{source_name}': {e}")
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
# ║ 🎯 compute_event_core_fingerprint                                  ║
# ║ Generates a stable hash for an event's identity (excluding time)  ║
# ╚════════════════════════════════════════════════════════════════════╝
def compute_event_core_fingerprint(event: dict) -> str:
    """
    Compute a fingerprint for an event's core identity, excluding timing details.
    This allows detection of the same event even when times are changed.
    """
    try:
        def clean(text: str) -> str:
            return " ".join(text.strip().split())

        summary = clean(event.get("summary", ""))
        location = clean(event.get("location", ""))
        description = clean(event.get("description", ""))
        
        # Include event ID if available for more precise matching
        event_id = event.get("id", "")

        # Core identity without timing
        core = {
            "summary": summary,
            "location": location,
            "description": description,
            "id": event_id
        }

        normalized_json = json.dumps(core, sort_keys=True)
        return hashlib.md5(normalized_json.encode("utf-8")).hexdigest()
    except Exception as e:
        logger.exception(f"Error computing event core fingerprint: {e}")
        return ""
