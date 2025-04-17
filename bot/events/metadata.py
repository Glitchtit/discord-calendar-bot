"""
metadata.py: Calendar metadata fetching and caching.
"""
from utils.logging import logger
from .google_api import service

_calendar_metadata_cache = {}

def fetch_google_calendar_metadata(calendar_id: str):
    cache_key = f"google_{calendar_id}"
    if cache_key in _calendar_metadata_cache:
        logger.debug(f"Using cached metadata for calendar {calendar_id}")
        return _calendar_metadata_cache[cache_key]
    if not service:
        logger.error(f"Google Calendar service not initialized, can't fetch metadata for {calendar_id}")
        return {"type": "google", "id": calendar_id, "name": calendar_id, "error": True}
    try:
        from .reload import retry_api_call
        retry_api_call(
            service.calendarList().insert(body={"id": calendar_id}).execute
        )
    except Exception as e:
        if "Already Exists" not in str(e):
            logger.warning(f"Couldn't subscribe to {calendar_id}: {e}")
    try:
        from .reload import retry_api_call
        cal = retry_api_call(
            service.calendarList().get(calendarId=calendar_id).execute
        )
        if not cal:
            logger.warning(f"Failed to get metadata for calendar {calendar_id} after retries")
            result = {"type": "google", "id": calendar_id, "name": calendar_id, "error": True}
        else:
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
        _calendar_metadata_cache[cache_key] = result
        return result
    except Exception as e:
        logger.warning(f"Error getting metadata for Google calendar {calendar_id}: {e}")
        result = {"type": "google", "id": calendar_id, "name": calendar_id, "error": True}
        _calendar_metadata_cache[cache_key] = result
        return result

def fetch_ics_calendar_metadata(url: str):
    cache_key = f"ics_{url}"
    if cache_key in _calendar_metadata_cache:
        logger.debug(f"Using cached metadata for ICS calendar {url}")
        return _calendar_metadata_cache[cache_key]
    import requests
    try:
        response = requests.head(url, timeout=5)
        response.raise_for_status()
        if "?" in url:
            url_parts = url.split("?")[0].split("/")
        else:
            url_parts = url.split("/")
        name = next((part for part in reversed(url_parts) if part), "ICS Calendar")
        if "%" in name:
            try:
                from urllib.parse import unquote
                name = unquote(name)
            except Exception:
                pass
        result = {"type": "ics", "id": url, "name": name}
        logger.debug(f"Loaded ICS calendar metadata: {name}")
        _calendar_metadata_cache[cache_key] = result
        return result
    except Exception as e:
        logger.warning(f"Error getting metadata for ICS calendar {url}: {e}")
        result = {"type": "ics", "id": url, "name": "ICS Calendar", "error": True}
        _calendar_metadata_cache[cache_key] = result
        return result
