import hashlib
import json
import requests
from datetime import datetime
from typing import Dict, List, Any
from ics import Calendar as ICS_Calendar
from src.core.logger import logger
from src.calendar.sources import service, retry_api_call
from src.ai.title_parser import simplify_event_title

# ╔════════════════════════════════════════════════════════════════════╗
# ║ 📆 Event Fetching                                                  ║
# ║ Retrieves events from Google or ICS sources                        ║
# ╚════════════════════════════════════════════════════════════════════╝

def get_google_events(start_date, end_date, calendar_id):
    """Fetch events from a Google Calendar."""
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
    """Fetch events from an ICS calendar."""
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
    """Get events from a calendar source."""
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
    """Generate a unique fingerprint for an event to detect changes."""
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