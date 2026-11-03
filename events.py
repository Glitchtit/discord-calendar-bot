import os
import re
import json
import hashlib
import requests
import time
import ssl
import threading
from collections import Counter
from datetime import datetime, timedelta, timezone, time as dtime
from typing import Dict, List, Tuple, Optional, Any
from ics import Calendar as ICS_Calendar # type: ignore
from google.oauth2 import service_account # type: ignore
from googleapiclient.discovery import build # type: ignore
from googleapiclient.errors import HttpError # type: ignore
from environ import GOOGLE_APPLICATION_CREDENTIALS, CALENDAR_SOURCES, USER_TAG_MAPPING
from log import logger
from ai_title_parser import simplify_event_title
from resilience import CalendarCircuitBreakers, retry_with_backoff
from utils import get_local_timezone

# Import TatSu exceptions for proper ICS parsing error handling
try:
    from tatsu.exceptions import ParseException, FailedParse # type: ignore[import-untyped]
except ImportError:
    # If TatSu is not available, define placeholder classes
    class ParseException(Exception):
        """Placeholder for TatSu ParseException when TatSu is not available."""
        pass
    class FailedParse(Exception):
        """Placeholder for TatSu FailedParse when TatSu is not available."""
        pass
    logger.warning("TatSu parser exceptions not available - some ICS parsing errors may not be caught optimally")

# ╔════════════════════════════════════════════════════════════════════╗
# ║ 🔐 Google Calendar API Initialization                             ║
# ║ Sets up credentials and API client for accessing Google Calendar ║
# ╚════════════════════════════════════════════════════════════════════╝
SERVICE_ACCOUNT_FILE = GOOGLE_APPLICATION_CREDENTIALS
SCOPES = ["https://www.googleapis.com/auth/calendar"]
EVENTS_FILE = "/data/events.json"

# In-memory cache
_calendar_metadata_cache = {}

# httplib2 inside the shared Google `service` is not thread-safe, and calls
# arrive from several asyncio.to_thread workers at once.
_google_lock = threading.Lock()

# Per-calendar circuit breakers (replaces manual _failed_calendars dict)
_calendar_breakers = CalendarCircuitBreakers(
    threshold=5, base_backoff=60, max_backoff=3600, auto_reset_after=3600
)

# Metrics tracking
_calendar_metrics = {
    "requests_total": 0,
    "requests_successful": 0,
    "requests_failed": 0,
    "parsing_errors": 0,
    "network_errors": 0,
    "auth_errors": 0,
    "events_processed": 0,
    "last_reset": datetime.now()
}

# ╔════════════════════════════════════════════════════════════════════╗
# ║ 🧹 ICS Content Preprocessing                                       ║
# ║ Cleans up common malformed patterns before parsing                 ║
# ╚════════════════════════════════════════════════════════════════════╝
def preprocess_ics_content(content: str, url: str) -> str:
    """
    Preprocess ICS content to fix common malformed patterns that cause parser errors.
    """
    
    original_length = len(content)
    logger.debug(f"Preprocessing ICS content from {url} ({original_length} chars)")
    
    # Normalize line endings first so the line-anchored patterns also match CRLF feeds
    content = content.replace('\r\n', '\n').replace('\r', '\n')

    # Empty DTSTART/DTEND values break the parser; park them in 1970 (outside every window)
    content = re.sub(r'^DTSTART:\s*$', 'DTSTART:19700101T000000Z', content, flags=re.MULTILINE)
    content = re.sub(r'^DTEND:\s*$', 'DTEND:19700101T010000Z', content, flags=re.MULTILINE)
    
    processed_length = len(content)
    if processed_length != original_length:
        logger.debug(f"ICS preprocessing for {url}: {original_length} -> {processed_length} chars")
    
    return content

_FLOATING_RE = re.compile(r"^(DTSTART|DTEND)(;VALUE=DATE-TIME)?:(\d{8}T\d{6})\r?$", re.MULTILINE)


def floating_times_to_utc(content: str) -> str:
    """RFC 5545 floating times (no Z, no TZID) are local wall-clock times, but the
    ics library parses them as UTC. Rewrite them as explicit UTC from the bot's timezone."""
    def to_utc(m):
        local = datetime.strptime(m.group(3), "%Y%m%dT%H%M%S").replace(tzinfo=get_local_timezone())
        return f"{m.group(1)}{m.group(2) or ''}:{local.astimezone(timezone.utc):%Y%m%dT%H%M%S}Z"
    return _FLOATING_RE.sub(to_utc, content)

# ╔════════════════════════════════════════════════════════════════════╗
# ║ 🔄 Circuit Breaker and Retry Logic                                ║
# ║ Prevents repeated attempts to failing calendar sources            ║
# ╚════════════════════════════════════════════════════════════════════╝
def is_ssl_error(exception: Exception) -> bool:
    """
    Check if an exception is an SSL-related error.
    
    Args:
        exception: The exception to check
        
    Returns:
        True if the exception is SSL-related, False otherwise
    """
    # Direct SSL error type check
    if isinstance(exception, ssl.SSLError):
        return True
    
    # Check OSError for SSL-related messages
    if isinstance(exception, OSError):
        error_msg = str(exception).lower()
        # Look for common SSL error patterns
        ssl_patterns = ['[ssl]', 'ssl error', 'ssl:', '_ssl.', 'record layer']
        return any(pattern in error_msg for pattern in ssl_patterns)
    
    return False

def is_calendar_circuit_open(calendar_id: str) -> bool:
    """Check if circuit breaker is open for a calendar source."""
    return _calendar_breakers.is_open(calendar_id)

def record_calendar_failure(calendar_id: str) -> None:
    """Record a failure for circuit breaker logic."""
    _calendar_breakers.record_failure(calendar_id)

def record_calendar_success(calendar_id: str) -> None:
    """Record successful operation to reset circuit breaker."""
    _calendar_breakers.record_success(calendar_id)

def update_metrics(metric_name: str, increment: int = 1):
    """Update calendar processing metrics."""
    if metric_name in _calendar_metrics:
        _calendar_metrics[metric_name] += increment
    
def get_metrics_summary() -> Dict[str, Any]:
    """Get current metrics summary."""
    now = datetime.now()
    duration = now - _calendar_metrics["last_reset"]
    
    success_rate = 0
    if _calendar_metrics["requests_total"] > 0:
        success_rate = (_calendar_metrics["requests_successful"] / _calendar_metrics["requests_total"]) * 100
    
    return {
        "duration_minutes": duration.total_seconds() / 60,
        "requests_total": _calendar_metrics["requests_total"],
        "requests_successful": _calendar_metrics["requests_successful"],
        "requests_failed": _calendar_metrics["requests_failed"],
        "success_rate_percent": round(success_rate, 1),
        "parsing_errors": _calendar_metrics["parsing_errors"],
        "network_errors": _calendar_metrics["network_errors"],
        "auth_errors": _calendar_metrics["auth_errors"],
        "events_processed": _calendar_metrics["events_processed"],
        "circuit_breakers_active": len(_calendar_breakers)
    }

def log_metrics_summary():
    """Log current metrics for monitoring."""
    summary = get_metrics_summary()
    if summary["requests_total"] > 0:  # Only log if there's been activity
        logger.info(
            f"Calendar metrics (last {summary['duration_minutes']:.1f}min): "
            f"{summary['requests_successful']}/{summary['requests_total']} requests successful "
            f"({summary['success_rate_percent']}%), "
            f"{summary['events_processed']} events processed, "
            f"{summary['parsing_errors']} parse errors, "
            f"{summary['network_errors']} network errors, "
            f"{summary['auth_errors']} auth errors, "
            f"{summary['circuit_breakers_active']} circuits open"
        )

def reset_metrics():
    """Reset metrics counters."""
    global _calendar_metrics
    _calendar_metrics = {
        "requests_total": 0,
        "requests_successful": 0,
        "requests_failed": 0,
        "parsing_errors": 0,
        "network_errors": 0,
        "auth_errors": 0,
        "events_processed": 0,
        "last_reset": datetime.now()
    }

def get_circuit_breaker_status() -> Dict[str, Any]:
    """Get current status of circuit breakers for monitoring."""
    return _calendar_breakers.get_status()

# Fallback directory for events if primary location is unavailable
FALLBACK_EVENTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

def _events_file() -> str:
    """Return a writable events snapshot path, preferring /data then local fallback."""
    primary_dir = os.path.dirname(EVENTS_FILE)
    if os.path.isdir(primary_dir) and os.access(primary_dir, os.W_OK):
        return EVENTS_FILE
    os.makedirs(FALLBACK_EVENTS_DIR, exist_ok=True)
    return os.path.join(FALLBACK_EVENTS_DIR, "events.json")

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
def _google_retryable(e: BaseException) -> bool:
    """Rate limits, server errors, SSL blips and corrupted HTTP responses are worth retrying."""
    if isinstance(e, HttpError):
        return e.resp.status >= 500 or e.resp.status == 429
    if isinstance(e, OSError):
        return is_ssl_error(e)
    return isinstance(e, (ValueError, AttributeError))


def retry_api_call(func, *args, max_retries=3, **kwargs):
    """Call a Google API function with backoff; None once retryable errors exhaust max_retries attempts."""
    def call():
        with _google_lock:
            return func(*args, **kwargs)
    try:
        return retry_with_backoff(call, max_retries=max_retries - 1, retry_if=_google_retryable)
    except Exception as e:
        if not _google_retryable(e):
            raise
        logger.error(f"All {max_retries} retries failed for API call: {e}")
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
            
        # Errors aren't cached: get_events retries them so a boot-time blip self-heals
        if not result.get("error"):
            _calendar_metadata_cache[cache_key] = result
        return result
        
    except Exception as e:
        logger.warning(f"Error getting metadata for Google calendar {calendar_id}: {e}")
        return {"type": "google", "id": calendar_id, "name": calendar_id, "error": True}
    
# Browser-like headers shared by the ICS validation probe and the real content
# fetch. Cloudflare-fronted hosts (e.g. inschool.fi/Wilma) challenge the default
# python-requests User-Agent, so both paths must look identical to the server.
_ICS_REQUEST_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (compatible; Calendar-Bot/1.0)',
    'Accept': 'text/calendar, text/plain, */*',
    'Accept-Encoding': 'identity',
}


def _derive_ics_name_from_url(url: str) -> str:
    """Derive a human-friendly calendar name from an ICS URL's last path segment."""
    parts = url.split("?")[0].split("/") if "?" in url else url.split("/")
    name = next((part for part in reversed(parts) if part), "ICS Calendar")
    if "%" in name:
        try:
            from urllib.parse import unquote
            name = unquote(name)
        except Exception:
            pass
    return name


def fetch_ics_calendar_metadata(url: str) -> Dict[str, Any]:
    """Fetch ICS Calendar metadata with enhanced validation and error handling."""
    # Check cache first
    cache_key = f"ics_{url}"
    if cache_key in _calendar_metadata_cache:
        cached_result = _calendar_metadata_cache[cache_key]
        if cached_result.get("error"):
            # Different cache expiry times based on error type
            error_type = cached_result.get("error_type", "unknown")
            if error_type in ["authentication", "forbidden", "not_found"]:
                # These are likely persistent config issues - cache for 6 hours
                cache_duration = 6 * 3600  # 6 hours
            elif error_type in ["method_not_allowed"]:
                # Server doesn't support HEAD/GET - cache for 24 hours
                cache_duration = 24 * 3600  # 24 hours
            else:
                # Network issues, timeouts - cache for 30 minutes
                cache_duration = 30 * 60  # 30 minutes
            
            if cached_result.get("cached_at", 0) + cache_duration < time.time():
                logger.debug(f"Cached {error_type} error expired for {url}, retrying validation")
                del _calendar_metadata_cache[cache_key]
            else:
                logger.debug(f"Using cached metadata for ICS calendar {url} (error cached for {cache_duration/3600:.1f}h)")
                return cached_result
        else:
            logger.debug(f"Using cached metadata for ICS calendar {url}")
            return cached_result
    
    try:
        # Validate via HEAD (cheap), falling back to a tiny ranged GET when the
        # server rejects HEAD. Both probes carry the same browser headers as the
        # real content fetch, and the whole probe is retried with backoff — so a
        # transient Cloudflare blip can't flip the calendar's name. (a)
        def _probe():
            response = requests.head(
                url, timeout=10, headers=_ICS_REQUEST_HEADERS, allow_redirects=True
            )
            if response.status_code == 405:
                logger.debug(f"HEAD not allowed for {url}, validating via ranged GET")
                response = requests.get(
                    url,
                    timeout=10,
                    headers={**_ICS_REQUEST_HEADERS, "Range": "bytes=0-1023"},
                    allow_redirects=True,
                )
                # 200 (range ignored) or 206 (partial) both mean the URL is good.
                if response.status_code in (200, 206):
                    return "GET-partial"
            response.raise_for_status()
            return "HEAD"

        validation_method = retry_with_backoff(_probe, max_retries=2, initial_delay=1.0)

        name = _derive_ics_name_from_url(url)
        result = {
            "type": "ics",
            "id": url,
            "name": name,
            "validation_method": validation_method,
            "cached_at": time.time(),
        }
        logger.debug(f"Loaded ICS calendar metadata: {name} (validated via {validation_method})")

        # Cache the result
        _calendar_metadata_cache[cache_key] = result
        return result

    except requests.exceptions.HTTPError as he:
        status_code = he.response.status_code if he.response is not None else 0
        if status_code == 401:
            logger.info(f"ICS calendar at {url} requires authentication (HTTP 401 Unauthorized)")
            error_type = "authentication"
            name = "ICS Calendar (Auth Required)"
        elif status_code == 403:
            logger.info(f"ICS calendar at {url} access forbidden (HTTP 403 Forbidden)")
            error_type = "forbidden"
            name = "ICS Calendar (Access Denied)"
        elif status_code == 404:
            logger.info(f"ICS calendar not found at {url} (HTTP 404 Not Found)")
            error_type = "not_found"
            name = "ICS Calendar (Not Found)"
        elif status_code == 405:
            logger.info(f"ICS calendar at {url} does not support HEAD/GET methods (HTTP 405)")
            error_type = "method_not_allowed"
            name = "ICS Calendar (Method Not Allowed)"
        else:
            # Unexpected/transient status (5xx, 429, ...) that survived retries.
            # Don't show a scary name or cache it as a sticky error: fall back to
            # the URL-derived name so events still render and it self-heals on the
            # next load. (c)
            logger.warning(
                f"Transient HTTP error validating ICS calendar URL {url} "
                f"(status {status_code}); using URL-derived name: {he}"
            )
            return {
                "type": "ics",
                "id": url,
                "name": _derive_ics_name_from_url(url),
                "validation_method": "unvalidated",
                "cached_at": time.time(),
            }

        result = {
            "type": "ics",
            "id": url,
            "name": name,
            "error": True,
            "error_type": error_type,
            "status_code": status_code,
            "cached_at": time.time()
        }
        _calendar_metadata_cache[cache_key] = result
        return result
        
    except requests.exceptions.Timeout as te:
        logger.warning(f"Timeout validating ICS calendar URL {url}: {te}")
        result = {
            "type": "ics", 
            "id": url, 
            "name": "ICS Calendar (Timeout)", 
            "error": True,
            "error_type": "timeout",
            "cached_at": time.time()
        }
        _calendar_metadata_cache[cache_key] = result
        return result
        
    except requests.exceptions.ConnectionError as ce:
        logger.warning(f"Connection error validating ICS calendar URL {url}: {ce}")
        result = {
            "type": "ics", 
            "id": url, 
            "name": "ICS Calendar (Connection Error)", 
            "error": True,
            "error_type": "connection",
            "cached_at": time.time()
        }
        _calendar_metadata_cache[cache_key] = result
        return result
        
    except requests.exceptions.RequestException as re:
        logger.warning(f"Request error validating ICS calendar URL {url}: {re}")
        result = {
            "type": "ics", 
            "id": url, 
            "name": "ICS Calendar (Request Error)", 
            "error": True,
            "error_type": "request",
            "cached_at": time.time()
        }
        _calendar_metadata_cache[cache_key] = result
        return result
        
    except Exception as e:
        logger.warning(f"Unexpected error getting metadata for ICS calendar {url}: {e}")
        result = {
            "type": "ics", 
            "id": url, 
            "name": "ICS Calendar (Unknown Error)", 
            "error": True,
            "error_type": "unknown",
            "cached_at": time.time()
        }
        _calendar_metadata_cache[cache_key] = result
        return result

# ╔════════════════════════════════════════════════════════════════════╗
# ║ 📚 Source Loader                                                   ║
# ║ Groups calendar sources by tag and loads them into memory         ║
# ╚════════════════════════════════════════════════════════════════════╝
# Mutated in place by load_calendar_sources(). Other modules import this dict
# directly, so it must never be rebound — only cleared and updated.
GROUPED_CALENDARS: Dict[str, List[Dict[str, Any]]] = {}

def load_calendar_sources(force_refresh: bool = False):
    """(Re)load calendar sources, updating GROUPED_CALENDARS in place.

    Called from on_ready and /reload rather than at import time, so
    environment validation runs before any network I/O. With
    force_refresh=True the metadata cache is dropped first so /reload
    actually re-fetches calendar names instead of serving cached entries.
    """
    try:
        logger.info("Loading calendar sources...")
        if force_refresh:
            _calendar_metadata_cache.clear()
        grouped = {}
        for ctype, cid, tag in parse_calendar_sources():
            try:
                meta = fetch_google_calendar_metadata(cid) if ctype == "google" else fetch_ics_calendar_metadata(cid)
                meta["tag"] = tag
                grouped.setdefault(tag, []).append(meta)
                logger.debug(f"Calendar loaded: {meta}")
            except Exception as e:
                logger.exception(f"Error loading calendar source {cid} for tag {tag}: {e}")
        GROUPED_CALENDARS.clear()
        GROUPED_CALENDARS.update(grouped)
        return GROUPED_CALENDARS
    except Exception as e:
        logger.exception(f"Error in load_calendar_sources: {e}")
        return GROUPED_CALENDARS

# ╔════════════════════════════════════════════════════════════════════╗
# ║ 💾 Event Snapshot Persistence                                      ║
# ╚════════════════════════════════════════════════════════════════════╝
def load_previous_events():
    try:
        path = _events_file()
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                logger.debug("Loaded previous event snapshot from disk.")
                return json.load(f)
    except json.JSONDecodeError:
        logger.warning("Previous events file corrupted. Starting fresh.")
    except Exception as e:
        logger.exception(f"Error loading previous events: {e}")
    return {}

def write_json_atomic(path: str, data, **dump_kwargs) -> None:
    """Write JSON via a temp file + rename, so a crash mid-write can't leave a truncated file."""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, **dump_kwargs)
    os.replace(tmp, path)


def save_current_events_for_key(key, events):
    try:
        logger.debug(f"Saving {len(events)} events under key: {key}")
        all_data = load_previous_events()
        all_data[key] = events
        write_json_atomic(_events_file(), all_data, ensure_ascii=False)
        logger.info(f"Saved events for key '{key}'.")
    except Exception as e:
        logger.exception(f"Error saving events for key {key}: {e}")

# ╔════════════════════════════════════════════════════════════════════╗
# ║ 📆 Event Fetching                                                  ║
# ║ Retrieves events from Google or ICS sources                        ║
# ╚════════════════════════════════════════════════════════════════════╝
def get_google_events(start_date, end_date, calendar_id):
    """Fetch events from Google Calendar. Returns None on failure, a list (maybe empty) on success."""
    if not service:
        logger.error(f"Google Calendar service not initialized, cannot fetch events for {calendar_id}")
        return None
    
    # Check circuit breaker
    if is_calendar_circuit_open(calendar_id):
        logger.debug(f"Circuit breaker open for Google calendar {calendar_id}, skipping")
        return None
    
    try:
        # Local midnight to local midnight, so "today" matches the bot's timezone, not UTC
        local_tz = get_local_timezone()
        start_utc = datetime.combine(start_date, dtime.min, tzinfo=local_tz).isoformat()
        end_utc = datetime.combine(end_date + timedelta(days=1), dtime.min, tzinfo=local_tz).isoformat()
        logger.debug(f"Fetching Google events for calendar {calendar_id} from {start_utc} to {end_utc}")
        update_metrics("requests_total")
        
        # Use retry_api_call to handle transient errors
        def api_call():
            return service.events().list(
                calendarId=calendar_id,
                timeMin=start_utc,
                timeMax=end_utc,
                singleEvents=True,
                orderBy="startTime",
                maxResults=2500,  # API max; the default page of 250 silently truncated busy calendars
            ).execute()
        
        result = retry_api_call(api_call, max_retries=3)
        
        if result is None:
            logger.warning(f"Failed to fetch events for calendar {calendar_id} after retries")
            return None
            
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
        
        # Record successful operation and update metrics
        record_calendar_success(calendar_id)
        update_metrics("requests_successful")
        update_metrics("events_processed", len(items))
        
        return items
        
    except (ssl.SSLError, OSError) as e:
        # Catch both ssl.SSLError and OSError for SSL-related socket errors
        if is_ssl_error(e):
            logger.error(f"SSL error fetching Google events from calendar {calendar_id}: {e}")
            logger.info("This may be a temporary network issue. The calendar will be retried on the next sync.")
            record_calendar_failure(calendar_id)
            update_metrics("requests_failed")
            update_metrics("network_errors")
            return None
        else:
            # Not an SSL error, re-raise to be handled by the general exception handler
            raise
    except requests.exceptions.ConnectionError as e:
        logger.error(f"Connection error fetching Google events from calendar {calendar_id}: {e}")
        logger.info("Network connection issue. The calendar will be retried on the next sync.")
        record_calendar_failure(calendar_id)
        update_metrics("requests_failed")
        update_metrics("network_errors")
        return None
    except requests.exceptions.Timeout as e:
        logger.error(f"Timeout error fetching Google events from calendar {calendar_id}: {e}")
        logger.info("Request timed out. The calendar will be retried on the next sync.")
        record_calendar_failure(calendar_id)
        update_metrics("requests_failed")
        update_metrics("network_errors")
        return None
    except HttpError as e:
        if e.resp.status in [403, 404]:
            logger.error(f"Access denied or calendar not found for {calendar_id}: {e}")
            logger.info("Check calendar permissions and ID validity.")
            record_calendar_failure(calendar_id)  # Permanent-ish failure
            update_metrics("requests_failed")
            update_metrics("auth_errors")
        else:
            logger.error(f"Google API error fetching events from calendar {calendar_id}: {e}")
            update_metrics("requests_failed")
            # Don't record failure for temporary API issues (rate limits, etc)
        return None
    except Exception as e:
        logger.exception(f"Unexpected error fetching Google events from calendar {calendar_id}: {e}")
        record_calendar_failure(calendar_id)
        update_metrics("requests_failed")
        return None

def _fetch_ics_content(url: str) -> str | None:
    """Fetch raw ICS content from a URL with retry logic and HTTP error handling.

    Returns the response text on success, or None on failure.
    Records circuit breaker state and metrics.
    """
    def fetch_calendar():
        response = requests.get(url, timeout=30, headers=_ICS_REQUEST_HEADERS, allow_redirects=True)

        http_error_handlers = {
            401: ("auth_errors", "Authentication required"),
            403: ("auth_errors", "Access forbidden"),
            404: (None, "Calendar not found"),
            405: (None, "Method not allowed"),
            429: ("network_errors", "Rate limited"),
        }
        if response.status_code in http_error_handlers:
            extra_metric, msg = http_error_handlers[response.status_code]
            logger.warning(f"{msg} for ICS calendar {url} (HTTP {response.status_code})")
            record_calendar_failure(url)
            update_metrics("requests_failed")
            if extra_metric:
                update_metrics(extra_metric)
            return []
        if response.status_code >= 500:
            logger.warning(f"Server error accessing ICS calendar {url} (HTTP {response.status_code})")
            raise requests.exceptions.HTTPError(f"Server error: {response.status_code}")

        response.raise_for_status()
        return response

    response = retry_with_backoff(fetch_calendar, max_retries=2, initial_delay=1.0)

    if isinstance(response, list):
        return None

    # Handle encoding issues
    try:
        # requests assumes ISO-8859-1 for text/* without a charset; ICS is UTF-8 by spec
        if "charset" not in response.headers.get("content-type", "").lower():
            response.encoding = "utf-8"
        return response.text
    except UnicodeDecodeError:
        logger.warning(f"Encoding error in ICS content from {url}, trying latin-1")
        try:
            return response.content.decode('latin-1')
        except UnicodeDecodeError:
            logger.warning(f"Failed to decode ICS content from {url}")
            return None


def _validate_ics_content(content: str, url: str) -> str | None:
    """Validate and preprocess ICS content. Returns cleaned content or None."""
    content = content.lstrip("\ufeff")  # a UTF-8 BOM would fail the BEGIN:VCALENDAR check
    if not content or len(content) < 50:
        logger.warning(f"ICS content too small or empty from {url}")
        return None
    if len(content) > 50_000_000:
        logger.warning(f"ICS content too large (>{len(content)/1_000_000:.1f}MB) from {url}")
        return None

    content_lower = content.lower()
    if content_lower.startswith('<!doctype') or '<html' in content_lower[:200]:
        logger.warning(f"Received HTML content instead of ICS from {url} - likely an authentication or access issue")
        return None
    if not content.startswith("BEGIN:VCALENDAR") or "END:VCALENDAR" not in content:
        logger.warning(f"Invalid ICS format (missing BEGIN/END markers) from {url}")
        logger.debug(f"Content preview: {content[:200]}...")
        return None
    content_bytes = content.encode('utf-8', errors='ignore')
    if b'\x00' in content_bytes or '\x00' in content:
        logger.warning(f"Suspicious content detected in ICS from {url}")
        return None

    # Preprocess unless explicitly disabled
    if os.getenv("DISABLE_ICS_PREPROCESSING", "false").lower() != "true":
        original = content
        try:
            content = preprocess_ics_content(content, url)
            logger.debug(f"ICS preprocessing completed for {url}")
        except Exception as e:
            logger.warning(f"Error preprocessing ICS content from {url}: {e}")
            content = original

    return content


def _parse_ics_calendar(content: str, url: str):
    """Parse ICS content into a Calendar object. Returns the calendar or None."""
    try:
        return ICS_Calendar(content)
    except ValueError as ve:
        error_msg = str(ve)
        if "time data" in error_msg or "does not match format" in error_msg:
            logger.warning(f"ICS datetime format error for {url}: Malformed date/time field - {ve}")
        else:
            logger.warning(f"ICS value parsing error for {url}: {ve}")
            if "mandatory DTSTART not found" in error_msg:
                logger.debug(f"ICS content sample from {url}: {content.split(chr(10))[:10]}")
    except (IndexError, TypeError, AttributeError, ImportError, MemoryError, RecursionError, UnicodeDecodeError) as e:
        logger.warning(f"ICS parsing error for {url}: {type(e).__name__} - {e}")
    except ParseException as pe:
        error_msg = str(pe)
        if "infinite left recursion" in error_msg.lower():
            logger.warning(f"ICS parser error for {url}: Infinite recursion in grammar")
        else:
            logger.warning(f"ICS parser error for {url}: {pe}")
    except FailedParse as fp:
        logger.warning(f"ICS parser error for {url}: Failed to parse - {fp}")
    except KeyboardInterrupt:
        raise
    except Exception as e:
        error_msg = str(e)
        if any(p in error_msg for p in ["ALPHADIGIT_MINUS_PLUS", "contentline", "TatSu", "grammar"]):
            logger.warning(f"ICS grammar/format error for {url}: {e}")
        else:
            logger.warning(f"ICS parser error for {url}: {e}")

    update_metrics("parsing_errors")
    return None


def _extract_ics_events(cal, url: str, start_date, end_date, has_uids: bool = True) -> list:
    """Extract and normalize events from a parsed ICS calendar.

    has_uids=False means the feed itself carries no UIDs; the ics library then
    invents a random one per parse, so a content-based id is used instead.
    """
    if not hasattr(cal, 'events') or cal.events is None:
        logger.warning(f"No events found in ICS calendar from {url}")
        return []

    try:
        cal_events = list(cal.events) if hasattr(cal.events, '__iter__') else []
    except (TypeError, ValueError, AttributeError) as e:
        logger.warning(f"Error accessing events from ICS calendar {url}: {e}")
        return []

    # A UID shared by several VEVENTs (a series plus moved occurrences) can't identify one event alone
    uid_counts = Counter(getattr(e, "uid", None) for e in cal_events) if has_uids else Counter()

    events = []
    try:
        for i, e in enumerate(cal_events):
            try:
                if not hasattr(e, 'begin') or not hasattr(e, 'end') or e.begin is None or e.end is None:
                    continue

                try:
                    all_day = bool(getattr(e, "all_day", False))
                    # Timed events are dated (and shown) in the bot's timezone; all-day events keep their calendar date
                    begin = e.begin if all_day else e.begin.to(get_local_timezone())
                    end = e.end if all_day else e.end.to(get_local_timezone())
                    first_day = begin.date()
                    # All-day ends are exclusive; a timed event ending at 00:00 doesn't touch that day
                    last_day = (end - timedelta(microseconds=1)).date() if end > begin else first_day
                except (AttributeError, ValueError, TypeError):
                    continue

                # Overlap, not start date: multi-day events show on every day they cover
                if last_day < start_date or first_day > end_date:
                    continue

                # Cap counts only in-window events; cal.events is an unordered set,
                # so capping before the date filter kept a random subset each fetch
                if len(events) >= 1000:
                    logger.warning(f"ICS calendar {url} has too many events in range (>1000), truncating")
                    break

                try:
                    original_title = getattr(e, 'name', None) or getattr(e, 'summary', None) or ""
                    location = getattr(e, 'location', None) or ""
                    description = getattr(e, 'description', None) or ""
                    if not isinstance(original_title, str):
                        original_title = str(original_title)
                    if not isinstance(location, str):
                        location = str(location)
                    if not isinstance(description, str):
                        description = str(description)
                    original_title = original_title[:500]
                    location = location[:200]
                    description = description[:1000]
                except Exception:
                    original_title, location, description = "Event", "", ""

                # A real UID is stable across time changes, so reschedules show as "changed"
                uid = getattr(e, "uid", None) if has_uids else None
                if uid and uid_counts[uid] > 1:
                    uid = f"{uid}|{e.begin}"
                id_source = uid or f"{original_title}|{e.begin}|{e.end}|{location}"

                try:
                    simplified_title = simplify_event_title(original_title) if original_title else "Event"
                except Exception:
                    simplified_title = original_title or "Event"

                try:
                    event = {
                        "summary": simplified_title,
                        "original_summary": original_title,
                        # Same shape as Google: {"date"} for all-day, local {"dateTime"} otherwise
                        "start": {"date": e.begin.date().isoformat()} if all_day else {"dateTime": begin.isoformat()},
                        "end": {"date": e.end.date().isoformat()} if all_day else {"dateTime": end.isoformat()},
                        "location": location,
                        "description": description,
                        "id": hashlib.md5(id_source.encode("utf-8")).hexdigest(),
                    }
                    events.append(event)
                    logger.debug(f"ICS title simplified: '{original_title}' -> '{simplified_title}'")
                except Exception as err:
                    logger.warning(f"Error creating event object from {url}: {err}")

            except KeyboardInterrupt:
                raise
            except Exception as event_error:
                logger.warning(f"Error processing individual event from {url}: {event_error}")
                continue
    except KeyboardInterrupt:
        raise
    except Exception as iteration_error:
        logger.warning(f"Error iterating through events from {url}: {iteration_error}")
        return []

    return events


def _deduplicate_events(events: list, url: str) -> list:
    """Deduplicate events by fingerprint."""
    seen_fps: set = set()
    deduped = []
    for e in events:
        try:
            fp = compute_event_fingerprint(e)
            if fp and fp not in seen_fps:
                seen_fps.add(fp)
                deduped.append(e)
            elif not fp:
                logger.debug(f"Could not fingerprint event, including anyway: {e.get('summary', 'Unknown')}")
                deduped.append(e)
        except Exception:
            deduped.append(e)
    logger.debug(f"Deduplicated to {len(deduped)} ICS events from {url}")
    return deduped


def get_ics_events(start_date, end_date, url):
    """Fetch events from an ICS calendar. Returns None on failure, a list (maybe empty) on success."""
    if is_calendar_circuit_open(url):
        logger.debug(f"Circuit breaker open for ICS calendar {url}, skipping")
        return None

    try:
        logger.debug(f"Fetching ICS events from {url}")
        update_metrics("requests_total")

        content = _fetch_ics_content(url)
        if content is None:
            return None

        content = _validate_ics_content(content, url)
        if content is None:
            return None
        content = floating_times_to_utc(content)  # correctness, so not behind DISABLE_ICS_PREPROCESSING

        cal = _parse_ics_calendar(content, url)
        if cal is None:
            return None

        # RRULE inside VTIMEZONE (DST rules) is normal; only an RRULE in a VEVENT means a series
        if re.search(r"^BEGIN:VEVENT$(?:(?!^END:VEVENT$).)*?^RRULE:", content, re.S | re.M):
            # shortcut: ics 0.7.2 doesn't expand RRULE, so repeating events show only their first
            # occurrence; switch to recurring-ical-events if a feed relies on them
            logger.warning(f"ICS feed {url} has repeating events (RRULE); only first occurrences are shown")
        # Only trust UIDs when every VEVENT has one (else ics invents random ones)
        has_uids = len(re.findall(r"^UID[:;]", content, re.M)) >= content.count("BEGIN:VEVENT")
        events = _extract_ics_events(cal, url, start_date, end_date, has_uids)
        deduped = _deduplicate_events(events, url)

        record_calendar_success(url)
        update_metrics("requests_successful")
        update_metrics("events_processed", len(deduped))
        return deduped

    except requests.exceptions.HTTPError as e:
        logger.warning(f"HTTP error fetching ICS calendar {url}: {e}")
        if e.response and e.response.status_code in [401, 403, 404, 405]:
            record_calendar_failure(url)
            update_metrics("requests_failed")
            if e.response.status_code in [401, 403]:
                update_metrics("auth_errors")
        else:
            update_metrics("requests_failed")
            update_metrics("network_errors")
        return None
    except requests.exceptions.RequestException as e:
        logger.warning(f"Network error fetching ICS calendar {url}: {e}")
        record_calendar_failure(url)
        update_metrics("requests_failed")
        update_metrics("network_errors")
        return None
    except (ssl.SSLError, OSError) as e:
        if is_ssl_error(e):
            logger.warning(f"SSL error fetching ICS calendar {url}: {e}")
            record_calendar_failure(url)
            update_metrics("requests_failed")
            update_metrics("network_errors")
            return None
        raise
    except Exception as e:
        logger.exception(f"Unexpected error fetching/parsing ICS calendar {url}: {e}")
        record_calendar_failure(url)
        update_metrics("requests_failed")
        return None

def get_events(source_meta, start_date, end_date):
    """Fetch events from a calendar source. Returns None when the fetch failed, so callers can tell it from an empty calendar."""
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
        
        # Metadata that failed at startup (e.g. a Cloudflare 403 on the probe) is
        # re-validated here so the real name comes back without /reload. The
        # events are fetched regardless: the probe and the content fetch can
        # disagree, and only the fetch decides "failed" (None) vs "empty" ([]).
        if source_meta.get("error"):
            fetch_meta = fetch_ics_calendar_metadata if source_type == "ics" else fetch_google_calendar_metadata
            fresh = fetch_meta(source_id)  # ICS errors stay cached 30min-24h, so this is cheap
            if not fresh.get("error") and fresh is not source_meta:
                # Recovered: update in place, since GROUPED_CALENDARS holds this dict
                logger.info(f"Calendar '{source_name}' validated again as '{fresh['name']}'")
                tag = source_meta.get("tag")
                source_meta.clear()
                source_meta.update(fresh, tag=tag)
                source_name = source_meta["name"]
        
        # Route to appropriate fetcher based on source type
        if source_type == "google":
            return get_google_events(start_date, end_date, source_id)
        elif source_type == "ics":
            events = get_ics_events(start_date, end_date, source_id)
            if events is not None and source_meta.get("error"):
                # The content fetch works even though the metadata probe failed (e.g. a
                # Cloudflare challenge on HEAD): drop the stale error and its scary name
                logger.info(f"Calendar '{source_name}' fetched fine; clearing its probe error")
                tag = source_meta.get("tag")
                source_meta.clear()
                source_meta.update(type="ics", id=source_id, name=_derive_ics_name_from_url(source_id),
                                   validation_method="content-fetch", cached_at=time.time(), tag=tag)
                _calendar_metadata_cache[f"ics_{source_id}"] = source_meta
            return events
        else:
            logger.warning(f"Unknown calendar source type '{source_type}' for source '{source_name}'")
            return []
            
    except Exception as e:
        source_name = source_meta.get("name", "Unknown") if isinstance(source_meta, dict) else "Unknown"
        logger.exception(f"Unexpected error getting events from source '{source_name}': {e}")
        return None

# ╔════════════════════════════════════════════════════════════════════╗
# ║ 🧬 compute_event_fingerprint                                       ║
# ║ Generates a stable hash for an event's core details               ║
# ╚════════════════════════════════════════════════════════════════════╝
def compute_event_fingerprint(event: dict) -> str:
    try:
        def normalize_time(val: str) -> str:
            # Naive UTC, so the same instant matches whatever offset (or all-day
            # midnight-UTC form) it was stored with
            dt = datetime.fromisoformat(val.replace("Z", "+00:00"))
            if dt.tzinfo:
                dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
            return dt.isoformat(timespec="minutes")

        def clean(text: str) -> str:
            return " ".join(text.strip().split())

        # Original title, not the AI-simplified one: the simplification can vary between runs
        summary = clean(event.get("original_summary") or event.get("summary", ""))
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

        # Original title, not the AI-simplified one: the simplification can vary between runs
        summary = clean(event.get("original_summary") or event.get("summary", ""))
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
