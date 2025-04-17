"""
event_fetching.py: Unified event fetching and source-specific logic.
"""
from datetime import date
from typing import Dict, List, Any
from utils.logging import logger
from .google_api import service
from .fingerprint import compute_event_fingerprint
import requests
from ics import Calendar as ICS_Calendar

def get_google_events(start_date, end_date, calendar_id):
    try:
        if not service:
            logger.error(f"Google Calendar service not initialized, can't fetch events for {calendar_id}")
            return []
        start_utc = start_date.isoformat() + "T00:00:00Z"
        end_utc = end_date.isoformat() + "T23:59:59Z"
        logger.debug(f"Fetching Google events for calendar {calendar_id} from {start_utc} to {end_utc}")
        from .reload import retry_api_call
        result = retry_api_call(
            lambda: service.events().list(
                calendarId=calendar_id,
                timeMin=start_utc,
                timeMax=end_utc,
                singleEvents=True,
                orderBy="startTime",
                maxResults=2500
            ).execute()
        )
        if result is None:
            logger.warning(f"Failed to fetch events for Google Calendar {calendar_id} after retries")
            return []
        items = result.get("items", [])
        for item in items:
            item["source"] = "google"
        logger.debug(f"Successfully fetched {len(items)} events from Google Calendar {calendar_id}")
        return items
    except Exception as e:
        logger.exception(f"Error fetching Google events from calendar {calendar_id}: {e}")
        return []

def get_ics_events(start_date, end_date, url):
    try:
        logger.debug(f"Fetching ICS events from {url}")
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        response.encoding = 'utf-8'
        cal = ICS_Calendar(response.text)
        if not hasattr(cal, 'events'):
            logger.warning(f"No events found in ICS calendar: {url}")
            return []
        logger.debug(f"Parsing {len(cal.events)} events from ICS calendar")
        events = []
        for e in cal.events:
            try:
                event_date = e.begin.date()
                if not (start_date <= event_date <= end_date):
                    continue
                id_source = f"{e.name}|{e.begin}|{e.end}|{e.location or ''}"
                import hashlib
                event_id = hashlib.md5(id_source.encode("utf-8")).hexdigest()
                event = {
                    "id": event_id,
                    "summary": e.name or "Unnamed Event",
                    "start": {"dateTime": e.begin.isoformat()},
                    "end": {"dateTime": e.end.isoformat()},
                    "location": e.location or "",
                    "description": e.description or "",
                    "source": "ics",
                    "status": "confirmed"
                }
                if e.all_day:
                    event["start"] = {"date": e.begin.date().isoformat()}
                    event["end"] = {"date": e.end.date().isoformat()}
                events.append(event)
            except Exception as inner_e:
                logger.warning(f"Error processing individual ICS event: {inner_e}")
                continue
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
    except Exception as e:
        logger.exception(f"Error parsing ICS calendar {url}: {e}")
        return []

def get_events(source_meta: Dict[str, str], start_date: date, end_date: date) -> List[Dict[str, Any]]:
    calendar_name = source_meta.get('name', 'Unknown Calendar')
    calendar_type = source_meta.get('type', 'unknown')
    calendar_id = source_meta.get('id', 'unknown-id')
    if not isinstance(start_date, date) or not isinstance(end_date, date):
        logger.error(f"Invalid date parameters for calendar {calendar_name}")
        return []
    if start_date > end_date:
        logger.error(f"Start date {start_date} is after end date {end_date} for calendar {calendar_name}")
        return []
    cache_key = f"{calendar_id}_{calendar_type}_{start_date.isoformat()}_{end_date.isoformat()}"
    def get_cached_events(key):
        from utils.cache import event_cache
        return event_cache.get(key)
    def set_cached_events(key, value):
        from utils.cache import event_cache
        event_cache.set(key, value)
    cached_events = get_cached_events(cache_key)
    if cached_events is not None:
        logger.debug(f"Cache hit for {calendar_name} events ({start_date} to {end_date})")
        return cached_events
    logger.debug(f"Cache miss for {calendar_name} events, fetching from {calendar_type} source")
    try:
        events = []
        if (calendar_type == "google"):
            events = get_google_events(start_date, end_date, calendar_id)
        elif (calendar_type == "ics"):
            events = get_ics_events(start_date, end_date, calendar_id)
        else:
            logger.warning(f"Unsupported calendar type: {calendar_type}")
            return []
        if events:
            events.sort(key=lambda e: e["start"].get("dateTime", e["start"].get("date", "")))
            logger.info(f"Successfully fetched {len(events)} events from {calendar_name} ({calendar_type})")
        else:
            logger.info(f"No events found for {calendar_name} in range {start_date} to {end_date}")
        result = events or []
        set_cached_events(cache_key, result)
        return result
    except Exception as e:
        logger.exception(f"Error fetching events from {calendar_name} ({calendar_type}): {e}")
        return []
