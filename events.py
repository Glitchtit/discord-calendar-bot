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
from resilience import CalendarCircuitBreakers, retry_with_backoff

# Import TatSu exceptions for proper ICS parsing error handling
try:
    from tatsu.exceptions import ParseException, FailedParse # type: ignore[import-untyped]
    TATSU_AVAILABLE = True
except ImportError:
    # If TatSu is not available, define placeholder classes
    class ParseException(Exception):
        """Placeholder for TatSu ParseException when TatSu is not available."""
        pass
    class FailedParse(Exception):
        """Placeholder for TatSu FailedParse when TatSu is not available."""
        pass
    TATSU_AVAILABLE = False
    logger.warning("TatSu parser exceptions not available - some ICS parsing errors may not be caught optimally")

# ╔════════════════════════════════════════════════════════════════════╗
# ║ 🔐 Google Calendar API Initialization                             ║
# ║ Sets up credentials and API client for accessing Google Calendar ║
# ╚════════════════════════════════════════════════════════════════════╝
SERVICE_ACCOUNT_FILE = GOOGLE_APPLICATION_CREDENTIALS
SCOPES = ["https://www.googleapis.com/auth/calendar"]
EVENTS_FILE = "/data/events.json"

# In-memory cache and error tracking
_calendar_metadata_cache = {}
_api_last_error_time = None
_api_error_count = 0
_API_BACKOFF_RESET = timedelta(minutes=30)
_MAX_API_ERRORS = 10

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
    import re
    
    original_length = len(content)
    logger.debug(f"Preprocessing ICS content from {url} ({original_length} chars)")
    
    # Apply only minimal, safe fixes to avoid breaking valid content
    # Only fix obviously broken patterns, be very conservative
    
    # Pattern 1: Only fix completely missing timezone on datetime formats that clearly need it
    # Only apply if the datetime is clearly malformed (has T but no timezone)
    content = re.sub(r'DTSTART:(\d{8}T\d{6})$', r'DTSTART:\1Z', content, flags=re.MULTILINE)
    content = re.sub(r'DTEND:(\d{8}T\d{6})$', r'DTEND:\1Z', content, flags=re.MULTILINE)
    
    # Pattern 2: Only fix empty values that would definitely break parsing
    content = re.sub(r'DTSTART:\s*$', 'DTSTART:19700101T000000Z', content, flags=re.MULTILINE)
    content = re.sub(r'DTEND:\s*$', 'DTEND:19700101T010000Z', content, flags=re.MULTILINE)
    
    # Only apply the most essential fixes
    
    # Remove only null bytes which definitely break parsing
    content = re.sub(r'[\x00]', '', content)
    
    # Only add missing VCALENDAR wrapper if completely missing
    if 'BEGIN:VCALENDAR' not in content and 'BEGIN:VEVENT' in content:
        logger.debug(f"ICS from {url} missing VCALENDAR wrapper, adding minimal wrapper")
        content = 'BEGIN:VCALENDAR\r\nVERSION:2.0\r\n' + content + '\r\nEND:VCALENDAR\r\n'
    
    # Skip the cleanup section for now - it might be too aggressive
    # Just ensure proper line endings
    content = content.replace('\r\n', '\n').replace('\r', '\n')
    
    processed_length = len(content)
    if processed_length != original_length:
        logger.debug(f"ICS preprocessing for {url}: {original_length} -> {processed_length} chars")
    
    return content

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
                
            # For rate limits and server errors, retry with backoff (max 30 seconds)
            backoff = min((2 ** attempt) + random.uniform(0, 1), 30.0)
            logger.warning(f"Retryable Google API error ({status_code}), attempt {attempt+1}/{max_retries}, backing off for {backoff:.2f}s: {str(e)}")
            time.sleep(backoff)
            last_exception = e
            
        except (ssl.SSLError, OSError) as e:
            # SSL errors and OS-level socket errors are retryable as they're often temporary network issues
            # OSError catches SSL errors that manifest as socket errors (e.g., [SSL] record layer failure)
            # Cap backoff to 30 seconds to prevent excessive blocking
            if is_ssl_error(e):
                backoff = min((2 ** attempt) + random.uniform(0, 1), 30.0)
                logger.warning(f"SSL error in API call, attempt {attempt+1}/{max_retries}, backing off for {backoff:.2f}s: {str(e)}")
                time.sleep(backoff)
                last_exception = e
            else:
                # Not an SSL error, re-raise to be handled by other exception handlers
                raise
            
        except requests.exceptions.RequestException as e:
            # Network errors are retryable
            backoff = min((2 ** attempt) + random.uniform(0, 1), 30.0)
            logger.warning(f"Network error in API call, attempt {attempt+1}/{max_retries}, backing off for {backoff:.2f}s: {str(e)}")
            time.sleep(backoff)
            last_exception = e
            
        except (ValueError, AttributeError) as e:
            # HTTP protocol errors (corrupted chunked encoding, etc.) are retryable
            # These can occur when the server sends malformed response data
            backoff = min((2 ** attempt) + random.uniform(0, 1), 30.0)
            logger.warning(f"HTTP protocol error in API call, attempt {attempt+1}/{max_retries}, backing off for {backoff:.2f}s: {str(e)}")
            time.sleep(backoff)
            last_exception = e
            
        except Exception as e:
            # Other errors are not retried - log with full traceback for debugging
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
        # Try HEAD request first for efficiency
        try:
            response = requests.head(url, timeout=10, allow_redirects=True)
            response.raise_for_status()
            validation_method = "HEAD"
        except requests.exceptions.HTTPError as he:
            # If HEAD fails with 405 Method Not Allowed, try GET with minimal data
            if he.response and he.response.status_code == 405:
                logger.debug(f"HEAD method not allowed for {url}, trying GET with range")
                try:
                    # Request only first 1KB to validate without downloading full calendar
                    headers = {'Range': 'bytes=0-1023'}
                    response = requests.get(url, timeout=10, headers=headers, allow_redirects=True)
                    # Don't raise for 206 (Partial Content) or 200 (if range not supported)
                    if response.status_code not in [200, 206]:
                        response.raise_for_status()
                    validation_method = "GET-partial"
                except requests.exceptions.HTTPError as ge:
                    if ge.response and ge.response.status_code in [401, 403]:
                        logger.info(f"ICS calendar at {url} requires authentication (HTTP {ge.response.status_code})")
                        result = {
                            "type": "ics", 
                            "id": url, 
                            "name": "ICS Calendar (Auth Required)", 
                            "error": True,
                            "error_type": "authentication",
                            "status_code": ge.response.status_code,
                            "cached_at": time.time()
                        }
                        _calendar_metadata_cache[cache_key] = result
                        return result
                    else:
                        raise  # Re-raise other HTTP errors
            else:
                raise  # Re-raise non-405 errors
        
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
                
        result = {
            "type": "ics", 
            "id": url, 
            "name": name, 
            "validation_method": validation_method,
            "cached_at": time.time()
        }
        logger.debug(f"Loaded ICS calendar metadata: {name} (validated via {validation_method})")
        
        # Cache the result
        _calendar_metadata_cache[cache_key] = result
        return result
        
    except requests.exceptions.HTTPError as he:
        status_code = he.response.status_code if he.response else 0
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
            logger.warning(f"HTTP error validating ICS calendar URL {url}: {he}")
            error_type = "http_error"
            name = "ICS Calendar (HTTP Error)"
            
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
    
    # Check circuit breaker
    if is_calendar_circuit_open(calendar_id):
        logger.debug(f"Circuit breaker open for Google calendar {calendar_id}, skipping")
        return []
    
    try:
        start_utc = start_date.isoformat() + "T00:00:00Z"
        end_utc = end_date.isoformat() + "T23:59:59Z"
        logger.debug(f"Fetching Google events for calendar {calendar_id} from {start_utc} to {end_utc}")
        update_metrics("requests_total")
        
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
            return []
        else:
            # Not an SSL error, re-raise to be handled by the general exception handler
            raise
    except requests.exceptions.ConnectionError as e:
        logger.error(f"Connection error fetching Google events from calendar {calendar_id}: {e}")
        logger.info("Network connection issue. The calendar will be retried on the next sync.")
        record_calendar_failure(calendar_id)
        update_metrics("requests_failed")
        update_metrics("network_errors")
        return []
    except requests.exceptions.Timeout as e:
        logger.error(f"Timeout error fetching Google events from calendar {calendar_id}: {e}")
        logger.info("Request timed out. The calendar will be retried on the next sync.")
        record_calendar_failure(calendar_id)
        update_metrics("requests_failed")
        update_metrics("network_errors")
        return []
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
        return []
    except Exception as e:
        logger.exception(f"Unexpected error fetching Google events from calendar {calendar_id}: {e}")
        record_calendar_failure(calendar_id)
        update_metrics("requests_failed")
        return []

def _fetch_ics_content(url: str) -> str | None:
    """Fetch raw ICS content from a URL with retry logic and HTTP error handling.

    Returns the response text on success, or None on failure.
    Records circuit breaker state and metrics.
    """
    headers = {
        'User-Agent': 'Mozilla/5.0 (compatible; Calendar-Bot/1.0)',
        'Accept': 'text/calendar, text/plain, */*',
        'Accept-Encoding': 'identity',
    }

    def fetch_calendar():
        response = requests.get(url, timeout=30, headers=headers, allow_redirects=True)

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
        response.encoding = response.encoding or 'utf-8'
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
    if "BEGIN:VEVENT" not in content:
        logger.debug(f"No VEVENT blocks found in ICS from {url} - calendar may be empty")
        return None

    content_bytes = content.encode('utf-8', errors='ignore')
    if b'\x00' in content_bytes or '\x00' in content:
        logger.warning(f"Suspicious content detected in ICS from {url}")
        return None

    # Preprocess unless explicitly disabled
    import os
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
    original_content = content
    try:
        return ICS_Calendar(content)
    except ValueError as ve:
        if "mandatory DTSTART not found" in str(ve) and content != original_content:
            logger.debug(f"Preprocessing may have caused parsing issue for {url}, trying original content")
            try:
                cal = ICS_Calendar(original_content)
                logger.info(f"Successfully parsed {url} with original content after preprocessing failed")
                return cal
            except Exception as e:
                logger.warning(f"Both preprocessed and original content failed for {url}: {e}")
        else:
            error_msg = str(ve)
            if "time data" in error_msg or "does not match format" in error_msg:
                logger.warning(f"ICS datetime format error for {url}: Malformed date/time field - {ve}")
            elif "mandatory DTSTART not found" in error_msg:
                logger.warning(f"ICS value parsing error for {url}: {ve}")
                logger.debug(f"ICS content sample from {url}: {content.split(chr(10))[:10]}")
            else:
                logger.warning(f"ICS value parsing error for {url}: {ve}")
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


def _extract_ics_events(cal, url: str, start_date, end_date) -> list:
    """Extract and normalize events from a parsed ICS calendar."""
    if not hasattr(cal, 'events') or cal.events is None:
        logger.warning(f"No events found in ICS calendar from {url}")
        return []

    try:
        cal_events = list(cal.events) if hasattr(cal.events, '__iter__') else []
    except (TypeError, ValueError, AttributeError) as e:
        logger.warning(f"Error accessing events from ICS calendar {url}: {e}")
        return []

    events = []
    try:
        for i, e in enumerate(cal_events):
            try:
                if i >= 1000:
                    logger.warning(f"ICS calendar {url} has too many events (>1000), truncating")
                    break

                if not hasattr(e, 'begin') or not hasattr(e, 'end') or e.begin is None or e.end is None:
                    continue

                try:
                    event_date = e.begin.date()
                except (AttributeError, ValueError, TypeError):
                    continue

                if not (start_date <= event_date <= end_date):
                    continue

                try:
                    original_title = (getattr(e, 'name', None) or getattr(e, 'summary', None) or "")
                    location = getattr(e, 'location', None) or ""
                    description = getattr(e, 'description', None) or ""
                    for attr in [original_title, location, description]:
                        if attr and not isinstance(attr, str):
                            attr = str(attr)
                    original_title = original_title[:500] if original_title else ""
                    location = location[:200] if location else ""
                    description = description[:1000] if description else ""
                except (UnicodeDecodeError, UnicodeEncodeError, Exception):
                    original_title, location, description = "Event", "", ""

                id_source = f"{original_title}|{e.begin}|{e.end}|{location}"

                try:
                    simplified_title = simplify_event_title(original_title) if original_title else "Event"
                except Exception:
                    simplified_title = original_title or "Event"

                try:
                    event = {
                        "summary": simplified_title,
                        "original_summary": original_title,
                        "start": {"dateTime": e.begin.isoformat()},
                        "end": {"dateTime": e.end.isoformat()},
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
    """Fetch events from ICS calendar with robust error handling and circuit breaker."""
    if is_calendar_circuit_open(url):
        logger.debug(f"Circuit breaker open for ICS calendar {url}, skipping")
        return []

    try:
        logger.debug(f"Fetching ICS events from {url}")
        update_metrics("requests_total")

        content = _fetch_ics_content(url)
        if content is None:
            return []

        content = _validate_ics_content(content, url)
        if content is None:
            return []

        cal = _parse_ics_calendar(content, url)
        if cal is None:
            return []

        events = _extract_ics_events(cal, url, start_date, end_date)
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
        return []
    except requests.exceptions.RequestException as e:
        logger.warning(f"Network error fetching ICS calendar {url}: {e}")
        record_calendar_failure(url)
        update_metrics("requests_failed")
        update_metrics("network_errors")
        return []
    except (ssl.SSLError, OSError) as e:
        if is_ssl_error(e):
            logger.warning(f"SSL error fetching ICS calendar {url}: {e}")
            record_calendar_failure(url)
            update_metrics("requests_failed")
            update_metrics("network_errors")
            return []
        raise
    except Exception as e:
        logger.exception(f"Unexpected error fetching/parsing ICS calendar {url}: {e}")
        record_calendar_failure(url)
        update_metrics("requests_failed")
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
        
        # Check if this source has validation errors and should be skipped
        if source_meta.get("error"):
            error_type = source_meta.get("error_type", "unknown")
            if error_type in ["authentication", "forbidden", "not_found", "method_not_allowed"]:
                # Only log this occasionally to avoid spam
                if source_meta.get("cached_at", 0) + 3600 < time.time():  # Log once per hour
                    logger.info(f"Skipping calendar '{source_name}' - {error_type} error (will retry in {(6 if error_type in ['authentication', 'forbidden', 'not_found'] else 24)}h)")
                    source_meta["cached_at"] = time.time()  # Update to reduce log frequency
                return []
            # For other error types (timeout, connection, etc.), still try to fetch
            # as they might be temporary issues
        
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
