import os
import json
import time
import ssl
import socket
import hashlib
import requests
from datetime import datetime, date, timedelta

from icalendar import Calendar as ICalParser
from google.oauth2 import service_account
from googleapiclient.discovery import build
from dateutil.rrule import rrulestr
from dateutil import tz
from zoneinfo import ZoneInfo
from pytz import UTC

from environ import GOOGLE_APPLICATION_CREDENTIALS, CALENDAR_SOURCES, USER_TAG_MAPPING
from log import logger

# ╔════════════════════════════════════════════════════════════════════╗
# 🔐 Google Calendar API Setup (No custom transport)
# ╚════════════════════════════════════════════════════════════════════╝
SERVICE_ACCOUNT_FILE = GOOGLE_APPLICATION_CREDENTIALS
SCOPES = ["https://www.googleapis.com/auth/calendar"]
EVENTS_FILE = "/data/events.json"
SNAPSHOT_DIR = "/data/snapshots"
METADATA_CACHE = "/data/calendar_meta.json"
os.makedirs(SNAPSHOT_DIR, exist_ok=True)

logger.debug(f"Loading Google credentials from: {SERVICE_ACCOUNT_FILE}")
credentials = service_account.Credentials.from_service_account_file(
    SERVICE_ACCOUNT_FILE, scopes=SCOPES
)
service = build("calendar", "v3", credentials=credentials)
socket.setdefaulttimeout(10)

# ╔════════════════════════════════════════════════════════════════════╗
# 👥 Tag Mapping
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
TAG_NAMES = {}
TAG_COLORS = {}

def get_name_for_tag(tag): return TAG_NAMES.get(tag, tag)
def get_color_for_tag(tag): return TAG_COLORS.get(tag, 0x95a5a6)

# ╔════════════════════════════════════════════════════════════════════╗
# 🕒 Time Utilities
# ╚════════════════════════════════════════════════════════════════════╝
def clean(text: str) -> str:
    return " ".join(text.strip().split()) if text else ""

def resolve_tz(tzid: str):
    try:
        return ZoneInfo(tzid)
    except Exception:
        logger.warning(f"Unknown TZID: {tzid}, defaulting to UTC.")
        return UTC

def normalize_time(val: str) -> str:
    if "Z" in val:
        val = val.replace("Z", "+00:00")
    dt = datetime.fromisoformat(val)
    return dt.astimezone(tz.UTC).strftime("%Y-%m-%dT%H:%M")

# ╔════════════════════════════════════════════════════════════════════╗
# 📄 Metadata Caching
# ╚════════════════════════════════════════════════════════════════════╝
def load_metadata_cache():
    if os.path.exists(METADATA_CACHE):
        try:
            with open(METADATA_CACHE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            logger.warning("Metadata cache corrupted. Starting fresh.")
    return {}

def save_metadata_cache(data):
    with open(METADATA_CACHE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)

METADATA = load_metadata_cache()

def fetch_google_calendar_metadata(calendar_id):
    cache_key = f"google:{calendar_id}"
    cached = METADATA.get(cache_key)
    if cached and (time.time() - cached.get("cached_at", 0) < 86400):
        return cached["data"]

    try:
        cal = service.calendarList().get(calendarId=calendar_id).execute()
        name = cal.get("summaryOverride") or cal.get("summary") or calendar_id
    except Exception as e:
        logger.warning(f"Couldn't get metadata for Google calendar {calendar_id}: {e}")
        name = calendar_id

    meta = {"type": "google", "id": calendar_id, "name": name}
    METADATA[cache_key] = {"cached_at": time.time(), "data": meta}
    save_metadata_cache(METADATA)
    return meta

def fetch_ics_calendar_metadata(url):
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
def get_google_events(start_date, end_date, calendar_id):
    start_utc = start_date.isoformat() + "T00:00:00Z"
    end_utc = end_date.isoformat() + "T23:59:59Z"
    logger.debug(f"Fetching Google events for {calendar_id} from {start_utc} to {end_utc}")

    try:
        result = service.events().list(
            calendarId=calendar_id,
            timeMin=start_utc,
            timeMax=end_utc,
            singleEvents=True,
            orderBy="startTime"
        ).execute()
    except Exception as e:
        logger.exception(f"Google API error for calendar {calendar_id}: {e}")
        return []

    events = []
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
            logger.warning(f"Skipped malformed Google event: {e} — {ex}")
    return events

# ╔════════════════════════════════════════════════════════════════════╗
# 📆 ICS Calendar Event Fetching
# ╚════════════════════════════════════════════════════════════════════╝
def get_ics_events(start_date: date, end_date: date, url: str):
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        content = response.content.strip()
        cal = ICalParser.from_ical(content)
    except Exception:
        logger.exception(f"Failed to fetch/parse ICS from {url}")
        return []

    events = []
    seen_ids = set()

    for component in cal.walk():
        if component.name != "VEVENT":
            continue
        try:
            dtstart = component.decoded("DTSTART")
            try:
                dtend = component.decoded("DTEND")
            except KeyError:
                dtend = dtstart + timedelta(hours=1)
                logger.warning(f"⏳ Missing DTEND; defaulted to 1 hour after DTSTART for {component.get('SUMMARY', 'Unknown')}")

            tzid = str(component.get("DTSTART").params.get("TZID", "UTC"))
            tzinfo = resolve_tz(tzid)

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
                exdates = {d.dt.date() for d in (ex if isinstance(ex, list) else [ex])}

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
            logger.exception("Skipping broken VEVENT in ICS.")
    return events


# ╔════════════════════════════════════════════════════════════════════╗
# 💾 Snapshot Persistence and Archiving
# ╚════════════════════════════════════════════════════════════════════╝

def load_previous_events():
    if os.path.exists(EVENTS_FILE):
        try:
            with open(EVENTS_FILE, "r", encoding="utf-8") as f:
                logger.debug("Loaded previous event snapshot from disk.")
                return json.load(f)
        except json.JSONDecodeError:
            logger.warning("Snapshot file corrupted. Starting fresh.")
    return {}

def save_current_events_for_key(key, events, versioned: bool = False):
    logger.debug(f"Saving {len(events)} events to snapshot key: {key}")
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
        with open(os.path.join(path, f"{date_str}.json"), "w", encoding="utf-8") as f:
            json.dump(events, f, ensure_ascii=False, indent=2)
        logger.info(f"📦 Archived snapshot for '{tag}' on {date_str}")

# ╔════════════════════════════════════════════════════════════════════╗
# 🧬 Event Fingerprinting
# ╚════════════════════════════════════════════════════════════════════╝

def compute_event_fingerprint(event: dict) -> str:
    return event.get("id") or hashlib.md5(json.dumps(event, sort_keys=True).encode()).hexdigest()

# ╔════════════════════════════════════════════════════════════════════╗
# 🗃️ Grouped Calendar Source Loader
# ╚════════════════════════════════════════════════════════════════════╝

def parse_calendar_sources():
    parsed = []
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
                logger.warning(f"Skipping calendar source without tag: {entry}")
        else:
            raise ValueError(f"Unsupported calendar source: {entry}")
    return parsed

def load_calendar_sources():
    logger.info("🔁 Loading calendar sources...")
    grouped = {}
    for ctype, cid, tag in parse_calendar_sources():
        meta = fetch_google_calendar_metadata(cid) if ctype == "google" else fetch_ics_calendar_metadata(cid)
        meta["tag"] = tag
        grouped.setdefault(tag, []).append(meta)
        logger.debug(f"Calendar loaded: {meta}")
    return grouped

GROUPED_CALENDARS = load_calendar_sources()

# ╔════════════════════════════════════════════════════════════════════╗
# 📡 Unified Event Fetching Interface
# ╚════════════════════════════════════════════════════════════════════╝

def get_events(source_meta, start_date, end_date):
    logger.debug(f"⏳ Fetching events from {source_meta['name']} ({source_meta['type']})")
    if source_meta["type"] == "google":
        return get_google_events(start_date, end_date, source_meta["id"])
    elif source_meta["type"] == "ics":
        return get_ics_events(start_date, end_date, source_meta["id"])
    return []
