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
from datetime import datetime, date, timedelta
from typing import Any, Dict, List, Optional, Tuple, Union

from icalendar import Calendar as ICalParser
from google.oauth2 import service_account
from googleapiclient.discovery import build
from dateutil.rrule import rrulestr
from dateutil import tz
from zoneinfo import ZoneInfo
from pytz import UTC

from environ import (
    GOOGLE_APPLICATION_CREDENTIALS,
    CALENDAR_SOURCES,
    USER_TAG_MAPPING
)
from log import logger

# ╔════════════════════════════════════════════════════════════════════╗
# 🔐 Google Calendar API Setup
# ╚════════════════════════════════════════════════════════════════════╝

SERVICE_ACCOUNT_FILE: str = GOOGLE_APPLICATION_CREDENTIALS
SCOPES: List[str] = ["https://www.googleapis.com/auth/calendar"]
EVENTS_FILE: str = "/data/events.json"
SNAPSHOT_DIR: str = "/data/snapshots"
METADATA_CACHE: str = "/data/calendar_meta.json"

os.makedirs(SNAPSHOT_DIR, exist_ok=True)

logger.debug(f"[events.py] Loading Google credentials from: {SERVICE_ACCOUNT_FILE}")
credentials = service_account.Credentials.from_service_account_file(
    SERVICE_ACCOUNT_FILE, scopes=SCOPES
)
service = build("calendar", "v3", credentials=credentials)
socket.setdefaulttimeout(10)


# ╔════════════════════════════════════════════════════════════════════╗
# 👥 Tag Mapping
# ╚════════════════════════════════════════════════════════════════════╝

def get_user_tag_mapping() -> Dict[int, str]:
    """
    Parses the USER_TAG_MAPPING environment variable, which maps
    Discord user IDs to calendar tags (e.g., "123456:T").

    Returns:
        A dictionary where keys are user IDs (int),
        and values are uppercase tag strings.
    """
    mapping: Dict[int, str] = {}
    for entry in USER_TAG_MAPPING.split(","):
        if ":" in entry:
            user_id_str, tag = entry.strip().split(":", 1)
            try:
                user_id = int(user_id_str)
                mapping[user_id] = tag.strip().upper()
            except ValueError:
                logger.warning(f"[events.py] Invalid user ID in USER_TAG_MAPPING: {entry}")
    return mapping

USER_TAG_MAP: Dict[int, str] = get_user_tag_mapping()
TAG_NAMES: Dict[str, str] = {}
TAG_COLORS: Dict[str, int] = {}

def get_name_for_tag(tag: str) -> str:
    """
    Returns a human-readable name for a given calendar tag, if available.
    Otherwise, returns the tag itself.
    """
    return TAG_NAMES.get(tag, tag)

def get_color_for_tag(tag: str) -> int:
    """
    Returns a Discord-compatible integer color code for a tag, if available.
    Otherwise, returns a default neutral color.
    """
    return TAG_COLORS.get(tag, 0x95A5A6)


# ╔════════════════════════════════════════════════════════════════════╗
# 🕒 Time & Date Utilities
# ╚════════════════════════════════════════════════════════════════════╝

def clean(text: str) -> str:
    """
    Trims extra whitespace from a string and collapses multiple spaces.

    Args:
        text: The input string to clean.

    Returns:
        A cleaned-up version of `text`.
    """
    return " ".join(text.strip().split()) if text else ""

def resolve_tz(tzid: str) -> ZoneInfo:
    """
    Attempts to resolve a TZID string to a valid time zone. Falls back to UTC if unknown.

    Args:
        tzid: A time zone identifier string (e.g., 'America/New_York').

    Returns:
        A ZoneInfo object, defaulting to UTC if tzid is invalid or unknown.
    """
    try:
        return ZoneInfo(tzid)
    except Exception:
        logger.warning(f"[events.py] Unknown TZID: {tzid}, defaulting to UTC.")
        return UTC

def normalize_time(val: str) -> str:
    """
    Converts an ISO 8601 date/time string (potentially with 'Z') into a consistent
    UTC-based format.

    Args:
        val: The date/time string to normalize (e.g. '2025-04-04T13:00:00Z').

    Returns:
        A string in '%Y-%m-%dT%H:%M' format, in UTC.
    """
    if "Z" in val:
        val = val.replace("Z", "+00:00")
    dt = datetime.fromisoformat(val)
    return dt.astimezone(tz.UTC).strftime("%Y-%m-%dT%H:%M")


# ╔════════════════════════════════════════════════════════════════════╗
# 📄 Metadata Caching
# ╚════════════════════════════════════════════════════════════════════╝

def load_metadata_cache() -> Dict[str, Dict[str, Any]]:
    """
    Loads calendar metadata cache from disk (JSON). If the file is missing
    or corrupted, returns an empty dictionary.

    Returns:
        A dictionary mapping "cache_key" -> {"cached_at": float, "data": {...}}
    """
    if os.path.exists(METADATA_CACHE):
        try:
            with open(METADATA_CACHE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            logger.warning("[events.py] Metadata cache corrupted. Starting fresh.")
    return {}

def save_metadata_cache(data: Dict[str, Any]) -> None:
    """
    Writes the provided metadata dictionary to the METADATA_CACHE file as JSON.

    Args:
        data: The metadata dictionary to save.
    """
    with open(METADATA_CACHE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)

METADATA: Dict[str, Any] = load_metadata_cache()

def fetch_google_calendar_metadata(calendar_id: str) -> Dict[str, str]:
    """
    Fetches metadata for a Google calendar ID, caching results for 24 hours.
    If the metadata is cached and not stale, returns the cached data.

    Args:
        calendar_id: The Google calendar ID.

    Returns:
        A dictionary containing at least { "type": "google", "id": calendar_id, "name": <name> }.
    """
    cache_key = f"google:{calendar_id}"
    cached = METADATA.get(cache_key)
    if cached and (time.time() - cached.get("cached_at", 0) < 86400):
        return cached["data"]

    try:
        cal = service.calendarList().get(calendarId=calendar_id).execute()
        name = cal.get("summaryOverride") or cal.get("summary") or calendar_id
    except Exception as e:
        logger.warning(f"[events.py] Couldn't get metadata for Google calendar {calendar_id}: {e}")
        name = calendar_id

    meta = {"type": "google", "id": calendar_id, "name": name}
    METADATA[cache_key] = {"cached_at": time.time(), "data": meta}
    save_metadata_cache(METADATA)
    return meta

def fetch_ics_calendar_metadata(url: str) -> Dict[str, str]:
    """
    Fetches metadata for an ICS URL, caching results for 24 hours.
    If the metadata is cached and not stale, returns the cached data.

    Args:
        url: The ICS feed URL.

    Returns:
        A dictionary containing at least { "type": "ics", "id": url, "name": <derived from URL> }.
    """
    cache_key = f"ics:{url}"
    cached = METADATA.get(cache_key)
    if cached and (time.time() - cached.get("cached_at", 0) < 86400):
        return cached["data"]

    name = url.split("/")[-1].split("?")[0] or "ICS Calendar"
    meta = {"type": "ics", "id": url, "name": name}
    METADATA[cache_key] = {"cached_at": time.time(), "data": meta}
    save_metadata_cache(METADATA)
    return meta


# ╔════════════════════════════════════════════════════════════════════╗
# 📆 Google Calendar Event Fetching
# ╚════════════════════════════════════════════════════════════════════╝

def get_google_events(
    start_date: date,
    end_date: date,
    calendar_id: str
) -> List[Dict[str, Any]]:
    """
    Queries the Google Calendar API for events between start_date and end_date.

    Args:
        start_date: The start of the date range (inclusive).
        end_date: The end of the date range (inclusive).
        calendar_id: The Google calendar ID.

    Returns:
        A list of event dictionaries in a standardized format.
    """
    start_utc = f"{start_date.isoformat()}T00:00:00Z"
    end_utc = f"{end_date.isoformat()}T23:59:59Z"
    logger.debug(f"[events.py] Fetching Google events for {calendar_id} from {start_utc} to {end_utc}")

    try:
        result = service.events().list(
            calendarId=calendar_id,
            timeMin=start_utc,
            timeMax=end_utc,
            singleEvents=True,
            orderBy="startTime"
        ).execute()
    except Exception as e:
        logger.exception(f"[events.py] Google API error for calendar {calendar_id}: {e}")
        return []

    events: List[Dict[str, Any]] = []
    seen_ids = set()

    for e in result.get("items", []):
        try:
            event_id = e["id"]
            if event_id in seen_ids:
                continue
            seen_ids.add(event_id)

            events.append({
                "id": event_id,
                "summary": clean(e.get("summary", "")),
                "description": clean(e.get("description", "")),
                "location": clean(e.get("location", "")),
                "start": e["start"],
                "end": e["end"],
                "allDay": "date" in e["start"]
            })
        except Exception as ex:
            logger.warning(f"[events.py] Skipped malformed Google event: {e} — {ex}")

    return events


# ╔════════════════════════════════════════════════════════════════════╗
# 📆 ICS Calendar Event Fetching
# ╚════════════════════════════════════════════════════════════════════╝

def fetch_ics_content(url: str, max_retries: int = 2) -> Optional[bytes]:
    """
    Attempts to fetch the raw ICS file content from the given URL,
    with a simple retry mechanism.

    Args:
        url: The ICS feed URL to fetch.
        max_retries: Maximum number of fetch attempts.

    Returns:
        The raw bytes of the ICS file if successful, otherwise None.
    """
    for attempt in range(1, max_retries + 1):
        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            return response.content.strip()
        except Exception as e:
            logger.error(f"[events.py] Failed to fetch ICS from {url} (attempt {attempt}): {e}")
            if attempt == max_retries:
                logger.error("[events.py] Max retries reached for ICS fetch.")
                return None
    return None  # Should not reach here if loop covers all attempts


def get_ics_events(
    start_date: date,
    end_date: date,
    url: str
) -> List[Dict[str, Any]]:
    """
    Downloads and parses an ICS feed for events between start_date and end_date.

    Args:
        start_date: The start of the date range (inclusive).
        end_date: The end of the date range (inclusive).
        url: The ICS feed URL.

    Returns:
        A list of event dictionaries in a standardized format.
    """
    content = fetch_ics_content(url, max_retries=2)
    if not content:
        logger.exception(f"[events.py] Failed to fetch/parse ICS from {url} after retries.")
        return []

    events: List[Dict[str, Any]] = []
    seen_ids = set()

    try:
        cal = ICalParser.from_ical(content)
    except Exception:
        logger.exception(f"[events.py] icalendar parsing error for {url}")
        return []

    for component in cal.walk():
        if component.name != "VEVENT":
            continue
        try:
            dtstart = component.decoded("DTSTART")
            try:
                dtend = component.decoded("DTEND")
            except KeyError:
                dtend = dtstart + timedelta(hours=1)
                logger.warning(f"[events.py] Missing DTEND; defaulted to 1 hour after DTSTART for {component.get('SUMMARY', 'Unknown')}")

            tzid = str(component.get("DTSTART").params.get("TZID", "UTC"))
            tzinfo = resolve_tz(tzid)

            # Check if it's a datetime or date
            if isinstance(dtstart, datetime):
                dtstart = dtstart.replace(tzinfo=tzinfo)
                dtend = dtend.replace(tzinfo=tzinfo)
                all_day = False
            else:
                all_day = True

            summary = str(component.get("SUMMARY", "Untitled"))
            location = str(component.get("LOCATION", ""))
            description = str(component.get("DESCRIPTION", ""))
            uid = str(component.get("UID", f"{summary}|{dtstart}|{dtend}|{location}"))
            if uid in seen_ids:
                continue
            seen_ids.add(uid)

            rrule = component.get("RRULE")
            exdates = set()
            if component.get("EXDATE"):
                ex = component.get("EXDATE")
                if not isinstance(ex, list):
                    ex = [ex]
                exdates = {d.dt.date() for d in ex}

            if rrule:
                rule = rrulestr(rrule.to_ical().decode(), dtstart=dtstart)
                for recur_dt in rule.between(start_date, end_date, inc=True):
                    if recur_dt.date() in exdates:
                        continue
                    recur_end = recur_dt + (dtend - dtstart)
                    events.append({
                        "id": uid + str(recur_dt),
                        "summary": summary,
                        "description": description,
                        "location": location,
                        "start": {"dateTime": recur_dt.isoformat()} if not all_day else {"date": recur_dt.date().isoformat()},
                        "end": {"dateTime": recur_end.isoformat()} if not all_day else {"date": recur_end.date().isoformat()},
                        "allDay": all_day
                    })
            else:
                # Single event with no recurrence
                if not (start_date <= dtstart.date() <= end_date):
                    continue
                events.append({
                    "id": uid,
                    "summary": summary,
                    "description": description,
                    "location": location,
                    "start": {"dateTime": dtstart.isoformat()} if not all_day else {"date": dtstart.date().isoformat()},
                    "end": {"dateTime": dtend.isoformat()} if not all_day else {"date": dtend.date().isoformat()},
                    "allDay": all_day
                })

        except Exception:
            logger.exception("[events.py] Skipping broken VEVENT in ICS.")

    return events


# ╔════════════════════════════════════════════════════════════════════╗
# 💾 Snapshot Persistence and Archiving
# ╚════════════════════════════════════════════════════════════════════╝

def load_previous_events() -> Dict[str, Any]:
    """
    Loads previously saved events from disk (JSON). If missing or corrupted,
    returns an empty dictionary.

    Returns:
        A dictionary structured as { 'some_key': [events], ... }
    """
    if os.path.exists(EVENTS_FILE):
        try:
            with open(EVENTS_FILE, "r", encoding="utf-8") as f:
                logger.debug("[events.py] Loaded previous event snapshot from disk.")
                return json.load(f)
        except json.JSONDecodeError:
            logger.warning("[events.py] Snapshot file corrupted. Starting fresh.")
    return {}

def save_current_events_for_key(key: str, events: List[Dict[str, Any]], versioned: bool = False) -> None:
    """
    Saves the current list of events under a specific key in the snapshot file,
    optionally creating a versioned daily archive.

    Args:
        key: A string key identifying the event set (e.g., 'tag_full').
        events: The list of event dictionaries to store.
        versioned: If True, also save a copy to a dated subdirectory for archival.
    """
    logger.debug(f"[events.py] Saving {len(events)} events to snapshot key: {key}")
    all_data = load_previous_events()
    all_data[key] = events
    os.makedirs(os.path.dirname(EVENTS_FILE), exist_ok=True)

    with open(EVENTS_FILE, "w", encoding="utf-8") as f:
        json.dump(all_data, f, ensure_ascii=False, indent=2)

    if versioned and "_full" in key:
        tag = key.replace("_full", "")
        date_str = date.today().isoformat()
        path = os.path.join(SNAPSHOT_DIR, tag)
        os.makedirs(path, exist_ok=True)
        archive_file_path = os.path.join(path, f"{date_str}.json")
        with open(archive_file_path, "w", encoding="utf-8") as f:
            json.dump(events, f, ensure_ascii=False, indent=2)
        logger.info(f"[events.py] 📦 Archived snapshot for '{tag}' on {date_str}")


def compute_event_fingerprint(event: Dict[str, Any]) -> str:
    """
    Computes a stable hash representing the given event, used to detect duplicates or changes.

    Args:
        event: A dictionary representing a calendar event.

    Returns:
        A string hash uniquely identifying this event.
    """
    return event.get("id") or hashlib.md5(json.dumps(event, sort_keys=True).encode()).hexdigest()


# ╔════════════════════════════════════════════════════════════════════╗
# 🗃️ Grouped Calendar Source Loader
# ╚════════════════════════════════════════════════════════════════════╝

def parse_calendar_sources() -> List[Tuple[str, str, str]]:
    """
    Parses CALENDAR_SOURCES environment variable (comma-separated),
    which should consist of entries like "google:CalendarID:TAG" or "ics:URL:TAG".

    Returns:
        A list of tuples (type, id_or_url, tag).
    """
    if not CALENDAR_SOURCES:
        logger.warning("[events.py] No CALENDAR_SOURCES provided.")
        return []

    parsed: List[Tuple[str, str, str]] = []
    for entry in CALENDAR_SOURCES.split(","):
        entry = entry.strip()
        if not entry:
            continue

        if entry.startswith("google:") or entry.startswith("ics:"):
            prefix, rest = entry.split(":", 1)
            if ":" in rest:
                id_or_url, tag = rest.rsplit(":", 1)
                parsed.append((prefix, id_or_url.strip(), tag.strip().upper()))
            else:
                logger.warning(f"[events.py] Skipping calendar source without tag: {entry}")
        else:
            logger.error(f"[events.py] Unsupported calendar source: {entry}")

    return parsed

def load_calendar_sources() -> Dict[str, List[Dict[str, str]]]:
    """
    Loads the calendar sources from environment, fetching metadata for each,
    and groups them by tag.

    Returns:
        A dictionary mapping tag -> list of metadata dicts like:
        { "type": ..., "id": ..., "name": ... }
    """
    logger.info("[events.py] 🔁 Loading calendar sources...")
    grouped: Dict[str, List[Dict[str, str]]] = {}
    for ctype, cid, tag in parse_calendar_sources():
        if ctype == "google":
            meta = fetch_google_calendar_metadata(cid)
        else:  # 'ics'
            meta = fetch_ics_calendar_metadata(cid)

        meta["tag"] = tag
        grouped.setdefault(tag, []).append(meta)
        logger.debug(f"[events.py] Calendar loaded: {meta}")

    return grouped

GROUPED_CALENDARS: Dict[str, List[Dict[str, str]]] = load_calendar_sources()


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
