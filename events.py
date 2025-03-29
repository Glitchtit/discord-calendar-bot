import os
import json
import hashlib
import requests
from datetime import datetime
from dateutil import tz
from ics import Calendar as ICS_Calendar
from google.oauth2 import service_account
from googleapiclient.discovery import build
from environ import GOOGLE_APPLICATION_CREDENTIALS, CALENDAR_SOURCES
from log import logger  # Shared logger

SERVICE_ACCOUNT_FILE = GOOGLE_APPLICATION_CREDENTIALS
SCOPES = ["https://www.googleapis.com/auth/calendar"]
EVENTS_FILE = "/data/events.json"

logger.debug(f"Loading Google credentials from: {SERVICE_ACCOUNT_FILE}")
credentials = service_account.Credentials.from_service_account_file(
    SERVICE_ACCOUNT_FILE, scopes=SCOPES
)
service = build("calendar", "v3", credentials=credentials)
logger.info("Google Calendar service initialized.")

def get_color_for_tag(tag):
    return {
        "T": 0x3498db,  # Blue (Thomas)
        "A": 0xe67e22,  # Orange (Anniina)
        "B": 0x9b59b6,  # Purple (Both)
    }.get(tag, 0x95a5a6)

def get_name_for_tag(tag):
    return {
        "T": "Thomas",
        "A": "Anniina",
        "B": "Both",
    }.get(tag, "Unknown")

def parse_calendar_sources():
    logger.debug("Parsing CALENDAR_SOURCES environment variable.")
    parsed = []
    for entry in CALENDAR_SOURCES.split(","):
        entry = entry.strip()
        if entry.startswith("google:") or entry.startswith("ics:"):
            prefix, rest = entry.split(":", 1)
            if ":" in rest:
                id_or_url, tag = rest.rsplit(":", 1)
                parsed.append((prefix, id_or_url.strip(), tag.strip().upper()))
                logger.debug(f"Parsed source: {prefix}:{id_or_url.strip()} with tag {tag.strip().upper()}")
    return parsed

def fetch_google_calendar_metadata(calendar_id):
    try:
        service.calendarList().insert(body={"id": calendar_id}).execute()
        logger.debug(f"Subscribed to Google calendar: {calendar_id}")
    except Exception as e:
        if "Already Exists" not in str(e):
            logger.warning(f"Couldn't subscribe to {calendar_id}: {e}")
    try:
        cal = service.calendarList().get(calendarId=calendar_id).execute()
        name = cal.get("summaryOverride") or cal.get("summary") or calendar_id
        logger.debug(f"Fetched metadata for Google calendar {calendar_id}: {name}")
    except Exception as e:
        logger.warning(f"Couldn't get calendar metadata for {calendar_id}: {e}")
        name = calendar_id
    return {"type": "google", "id": calendar_id, "name": name}

def fetch_ics_calendar_metadata(url):
    name = url.split("/")[-1].split("?")[0] or "ICS Calendar"
    logger.debug(f"Using name '{name}' for ICS calendar {url}")
    return {"type": "ics", "id": url, "name": name}

def load_calendar_sources():
    logger.info("Loading calendar sources...")
    grouped = {"T": [], "A": [], "B": []}
    for ctype, cid, tag in parse_calendar_sources():
        meta = fetch_google_calendar_metadata(cid) if ctype == "google" else fetch_ics_calendar_metadata(cid)
        meta["tag"] = tag
        grouped.setdefault(tag, []).append(meta)
        logger.debug(f"Loaded calendar: {meta}")
    return grouped

GROUPED_CALENDARS = load_calendar_sources()

def load_previous_events():
    if os.path.exists(EVENTS_FILE):
        with open(EVENTS_FILE, "r", encoding="utf-8") as f:
            try:
                logger.debug("Loading previous events from disk...")
                return json.load(f)
            except json.JSONDecodeError:
                logger.warning("Failed to decode previous events file. Returning empty.")
    return {}

def save_current_events_for_key(key, events):
    logger.debug(f"Saving {len(events)} events under key: {key}")
    all_data = load_previous_events()
    all_data[key] = events
    with open(EVENTS_FILE, "w", encoding="utf-8") as f:
        json.dump(all_data, f, ensure_ascii=False)
        logger.info(f"Saved events for key '{key}' to {EVENTS_FILE}")

def get_google_events(start_date, end_date, calendar_id):
    logger.debug(f"Fetching Google events from {start_date} to {end_date} for calendar: {calendar_id}")
    start_utc = start_date.isoformat() + "T00:00:00Z"
    end_utc = end_date.isoformat() + "T23:59:59Z"
    result = service.events().list(
        calendarId=calendar_id,
        timeMin=start_utc,
        timeMax=end_utc,
        singleEvents=True,
        orderBy="startTime"
    ).execute()
    items = result.get("items", [])
    logger.info(f"Retrieved {len(items)} Google events for {calendar_id}")
    return items

def get_ics_events(start_date, end_date, url):
    logger.debug(f"Fetching ICS events from {url} for {start_date} to {end_date}")
    try:
        response = requests.get(url)
        response.encoding = 'utf-8'
        cal = ICS_Calendar(response.text)
        events = []
        for e in cal.events:
            if start_date <= e.begin.date() <= end_date:
                id_source = f"{e.name}|{e.begin}|{e.end}|{e.location or ''}"
                event_id = hashlib.md5(id_source.encode("utf-8")).hexdigest()
                events.append({
                    "summary": e.name,
                    "start": {"dateTime": e.begin.isoformat()},
                    "end": {"dateTime": e.end.isoformat()},
                    "location": e.location or "",
                    "description": e.description or "",
                    "id": event_id
                })
        logger.info(f"Retrieved {len(events)} ICS events from {url}")
        return events
    except Exception as e:
        logger.exception(f"Could not fetch or parse ICS calendar: {url}")
        return []

def get_events(source_meta, start_date, end_date):
    logger.debug(f"Getting events for source: {source_meta['name']}")
    if source_meta["type"] == "google":
        return get_google_events(start_date, end_date, source_meta["id"])
    elif source_meta["type"] == "ics":
        return get_ics_events(start_date, end_date, source_meta["id"])
    return []
