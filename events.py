import os
import json
import hashlib
import requests
from datetime import datetime
from ics import Calendar as ICS_Calendar
from google.oauth2 import service_account
from googleapiclient.discovery import build
from environ import GOOGLE_APPLICATION_CREDENTIALS, CALENDAR_SOURCES, USER_TAG_MAPPING
from log import logger

# ╔════════════════════════════════════════════════════════════════════╗
# ║ 🔐 Google Calendar API Initialization                             ║
# ║ Sets up credentials and API client for accessing Google Calendar ║
# ╚════════════════════════════════════════════════════════════════════╝
SERVICE_ACCOUNT_FILE = GOOGLE_APPLICATION_CREDENTIALS
SCOPES = ["https://www.googleapis.com/auth/calendar"]
EVENTS_FILE = "/data/events.json"

logger.debug(f"Loading Google credentials from: {SERVICE_ACCOUNT_FILE}")
credentials = service_account.Credentials.from_service_account_file(
    SERVICE_ACCOUNT_FILE, scopes=SCOPES
)
service = build("calendar", "v3", credentials=credentials)
logger.info("Google Calendar service initialized.")

# ╔════════════════════════════════════════════════════════════════════╗
# ║ 👥 Tag Mapping (User ID → Tag)                                     ║
# ╚════════════════════════════════════════════════════════════════════╝
def get_user_tag_mapping():
    mapping = {}
    for entry in USER_TAG_MAPPING.split(","):
        if ":" in entry:
            user_id, tag = entry.strip().split(":", 1)
            try:
                mapping[int(user_id)] = tag.strip().upper()
            except ValueError:
                logger.warning(f"Invalid user ID in USER_TAG_MAPPING: {entry}")
    return mapping

USER_TAG_MAP = get_user_tag_mapping()

# Populated during bot startup
TAG_NAMES = {}
TAG_COLORS = {}

def get_name_for_tag(tag):
    return TAG_NAMES.get(tag, tag)

def get_color_for_tag(tag):
    return TAG_COLORS.get(tag, 0x95a5a6)  # Default gray color

# ╔════════════════════════════════════════════════════════════════════╗
# ║ 📦 Calendar Source Parsing                                         ║
# ║ Parses CALENDAR_SOURCES into structured source info               ║
# ╚════════════════════════════════════════════════════════════════════╝
def parse_calendar_sources():
    parsed = []
    for entry in CALENDAR_SOURCES.split(","):
        entry = entry.strip()
        if entry.startswith("google:") or entry.startswith("ics:"):
            prefix, rest = entry.split(":", 1)
            if ":" in rest:
                id_or_url, tag = rest.rsplit(":", 1)
                parsed.append((prefix, id_or_url.strip(), tag.strip().upper()))
                logger.debug(f"Parsed calendar source: {prefix}:{id_or_url.strip()} (tag={tag.strip().upper()})")
    return parsed

# ╔════════════════════════════════════════════════════════════════════╗
# ║ 📄 Calendar Metadata Fetching                                     ║
# ╚════════════════════════════════════════════════════════════════════╝
def fetch_google_calendar_metadata(calendar_id):
    try:
        service.calendarList().insert(body={"id": calendar_id}).execute()
    except Exception as e:
        if "Already Exists" not in str(e):
            logger.warning(f"Couldn't subscribe to {calendar_id}: {e}")
    try:
        cal = service.calendarList().get(calendarId=calendar_id).execute()
        name = cal.get("summaryOverride") or cal.get("summary") or calendar_id
    except Exception as e:
        logger.warning(f"Couldn't get metadata for Google calendar {calendar_id}: {e}")
        name = calendar_id
    logger.debug(f"Loaded Google calendar metadata: {name}")
    return {"type": "google", "id": calendar_id, "name": name}

def fetch_ics_calendar_metadata(url):
    name = url.split("/")[-1].split("?")[0] or "ICS Calendar"
    logger.debug(f"Loaded ICS calendar metadata: {name}")
    return {"type": "ics", "id": url, "name": name}

# ╔════════════════════════════════════════════════════════════════════╗
# ║ 📚 Source Loader                                                   ║
# ║ Groups calendar sources by tag and loads them into memory         ║
# ╚════════════════════════════════════════════════════════════════════╝
def load_calendar_sources():
    logger.info("Loading calendar sources...")
    grouped = {}
    for ctype, cid, tag in parse_calendar_sources():
        meta = fetch_google_calendar_metadata(cid) if ctype == "google" else fetch_ics_calendar_metadata(cid)
        meta["tag"] = tag
        grouped.setdefault(tag, []).append(meta)
        logger.debug(f"Calendar loaded: {meta}")
    return grouped

GROUPED_CALENDARS = load_calendar_sources()

# ╔════════════════════════════════════════════════════════════════════╗
# ║ 💾 Event Snapshot Persistence                                      ║
# ╚════════════════════════════════════════════════════════════════════╝
def load_previous_events():
    if os.path.exists(EVENTS_FILE):
        try:
            with open(EVENTS_FILE, "r", encoding="utf-8") as f:
                logger.debug("Loaded previous event snapshot from disk.")
                return json.load(f)
        except json.JSONDecodeError:
            logger.warning("Previous events file corrupted. Starting fresh.")
    return {}

def save_current_events_for_key(key, events):
    logger.debug(f"Saving {len(events)} events under key: {key}")
    all_data = load_previous_events()
    all_data[key] = events
    with open(EVENTS_FILE, "w", encoding="utf-8") as f:
        json.dump(all_data, f, ensure_ascii=False)
    logger.info(f"Saved events for key '{key}'.")

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
        logger.debug(f"Fetched {len(items)} Google events for {calendar_id}")
        return items
    except Exception as e:
        logger.exception(f"Error fetching Google events from calendar {calendar_id}")
        return []

def get_ics_events(start_date, end_date, url):
    try:
        logger.debug(f"Fetching ICS events from {url}")
        response = requests.get(url)
        response.encoding = 'utf-8'
        cal = ICS_Calendar(response.text)
        events = []
        for e in cal.events:
            if start_date <= e.begin.date() <= end_date:
                id_source = f"{e.name}|{e.begin}|{e.end}|{e.location or ''}"
                event = {
                    "summary": e.name,
                    "start": {"dateTime": e.begin.isoformat()},
                    "end": {"dateTime": e.end.isoformat()},
                    "location": e.location or "",
                    "description": e.description or "",
                    "id": hashlib.md5(id_source.encode("utf-8")).hexdigest()
                }
                events.append(event)

        seen_fps = set()
        deduped = []
        for e in events:
            fp = compute_event_fingerprint(e)
            if fp not in seen_fps:
                seen_fps.add(fp)
                deduped.append(e)
        logger.debug(f"Deduplicated to {len(deduped)} ICS events")
        return deduped
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
