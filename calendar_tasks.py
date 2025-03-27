# calendar_tasks.py

import os
import json
import hashlib
import requests
from datetime import datetime
from dateutil import tz
from ics import Calendar as ICS_Calendar

# Google API libraries
from google.oauth2 import service_account
from googleapiclient.discovery import build

# If you want to generate a catgirl greeting, import from ai.py
# (Remove if you no longer want a greeting function.)
from ai import generate_greeting, generate_image_prompt, generate_image

# 1) --- Configuration / Environment ---
SERVICE_ACCOUNT_FILE = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "service_account.json")
SCOPES = ["https://www.googleapis.com/auth/calendar"]
EVENTS_FILE = os.environ.get("EVENTS_FILE", "events.json")

# This key is where we'll store *all* events (rather than date-bounded sets).
ALL_EVENTS_KEY = "ALL_EVENTS"

# Build a Google Calendar API client
credentials = service_account.Credentials.from_service_account_file(
    SERVICE_ACCOUNT_FILE, scopes=SCOPES
)
service = build("calendar", "v3", credentials=credentials)


# 2) --- Parsing environment for calendar sources ---
def parse_calendar_sources():
    """
    Reads CALENDAR_SOURCES from env, expecting entries like:
      google:someone@example.com:T
      ics:https://domain.com/something.ics:B
    Returns a list of tuples: (ctype, id/url, tag).
    """
    sources_str = os.environ.get("CALENDAR_SOURCES", "")
    results = []
    for entry in sources_str.split(","):
        entry = entry.strip()
        if not entry:
            continue
        if entry.startswith("google:") or entry.startswith("ics:"):
            prefix, rest = entry.split(":", 1)
            if ":" in rest:
                # e.g. "someone@example.com:T"
                cal_id_or_url, tag = rest.rsplit(":", 1)
                results.append((prefix, cal_id_or_url.strip(), tag.strip().upper()))
    return results


# 3) --- Calendar Source Registration ---
def fetch_google_calendar_metadata(calendar_id: str):
    """
    Attempts to subscribe to the Google calendar and fetch its metadata (display name, etc.).
    """
    try:
        service.calendarList().insert(body={"id": calendar_id}).execute()
    except Exception as e:
        if "Already Exists" not in str(e):
            print(f"[WARNING] Could not subscribe to {calendar_id}: {e}")

    try:
        cal = service.calendarList().get(calendarId=calendar_id).execute()
        name = cal.get("summaryOverride") or cal.get("summary") or calendar_id
    except Exception as e:
        print(f"[WARNING] Could not retrieve metadata for {calendar_id}: {e}")
        name = calendar_id

    return {
        "type": "google",
        "id": calendar_id,
        "name": name
    }


def fetch_ics_calendar_metadata(url: str):
    """
    For ICS calendars, just store the URL and derive a name from the filename if possible.
    """
    name = url.split("/")[-1].split("?")[0] or "ICS Calendar"
    return {
        "type": "ics",
        "id": url,
        "name": name
    }


def load_calendar_sources():
    """
    Groups all found calendars by their tag: T / A / B / etc.
    Returns a dict like:
      {
        "T": [ {type: "google", id: "...", name: "...", tag: "T"}, ... ],
        "A": [...],
        "B": [...],
      }
    """
    grouped = {}
    for ctype, cal_id_or_url, tag in parse_calendar_sources():
        # fetch metadata
        if ctype == "google":
            meta = fetch_google_calendar_metadata(cal_id_or_url)
        elif ctype == "ics":
            meta = fetch_ics_calendar_metadata(cal_id_or_url)
        else:
            continue

        meta["tag"] = tag
        grouped.setdefault(tag, []).append(meta)
    return grouped


# Store these grouped calendars in a global for easy re-use
GROUPED_CALENDARS = load_calendar_sources()


# 4) --- Utility: local JSON storing / loading ---
def load_previous_events() -> dict:
    """
    Loads previously stored data from EVENTS_FILE as a dict.
    Example structure might look like:
      {
        "ALL_EVENTS": [ ... ],
        ...
      }
    """
    if os.path.exists(EVENTS_FILE):
        try:
            with open(EVENTS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError:
            pass
    return {}


def save_current_events_for_key(key: str, events: list):
    """
    Save 'events' under 'key' in EVENTS_FILE, preserving any other data in that file.
    """
    all_data = load_previous_events()
    all_data[key] = events
    with open(EVENTS_FILE, "w", encoding="utf-8") as f:
        json.dump(all_data, f, ensure_ascii=False, indent=2)


# 5) --- Entire Calendar Fetching (Google + ICS) ---
def get_all_calendar_events() -> list:
    """
    Loads *all* events from each calendar source, ignoring date boundaries.
    For Google, we fetch from 1970-01-01 to 2100-01-01.
    For ICS, we parse all events in the .ics file.
    Returns a combined list of event dicts, each with an 'id' to detect changes.
    Each event is expected to have fields like:
      {
        'id': ...,
        'summary': ...,
        'start': {'dateTime': ...},
        'end': {'dateTime': ...},
        'location': ...,
        'description': ...
      }
    """
    # Flatten out all calendars from GROUPED_CALENDARS
    # e.g. { "T": [...], "A": [...], ... }
    sources = []
    for cals_list in GROUPED_CALENDARS.values():
        sources.extend(cals_list)

    all_events = []
    for meta in sources:
        if meta["type"] == "google":
            # large range for "all events"
            start_utc = "1970-01-01T00:00:00Z"
            end_utc   = "2100-01-01T23:59:59Z"

            try:
                # fetch everything
                items = service.events().list(
                    calendarId=meta["id"],
                    timeMin=start_utc,
                    timeMax=end_utc,
                    singleEvents=True,
                    orderBy="startTime"
                ).execute().get("items", [])
                all_events.extend(items)
            except Exception as exc:
                print(f"[ERROR] Couldn't fetch from Google calendar '{meta['id']}': {exc}")

        elif meta["type"] == "ics":
            url = meta["id"]
            try:
                response = requests.get(url)
                response.raise_for_status()
                response.encoding = 'utf-8'
                ics_cal = ICS_Calendar(response.text)
                for e in ics_cal.events:
                    # build an event record
                    id_source = f"{e.name}|{e.begin}|{e.end}|{e.location or ''}"
                    event_id = hashlib.md5(id_source.encode("utf-8")).hexdigest()
                    all_events.append({
                        "id": event_id,
                        "summary": e.name,
                        "start": {"dateTime": e.begin.isoformat()},
                        "end": {"dateTime": e.end.isoformat()},
                        "location": e.location or "",
                        "description": e.description or ""
                    })
            except Exception as exc:
                print(f"[ERROR] Couldn't fetch ICS from '{url}': {exc}")

    # Optionally, sort them by start date/time
    def sort_key(evt):
        # prefer dateTime if it exists, else date
        maybe_start = evt["start"].get("dateTime", evt["start"].get("date", "2099-12-31"))
        return maybe_start
    all_events.sort(key=sort_key)

    return all_events


# 6) --- Detecting Changes in the Full Data Set ---
def extract_comparable_fields(event: dict):
    """
    We compare these fields to detect whether an event changed:
    start, end, summary, location, and description.
    """
    start = event["start"].get("dateTime", event["start"].get("date", ""))
    end = event["end"].get("dateTime", event["end"].get("date", ""))
    summary = event.get("summary", "")
    location = event.get("location", "")
    description = event.get("description", "")
    return (start, end, summary, location, description)

def detect_changes(old_events: list, new_events: list) -> list[str]:
    """
    Compares two lists of events by their 'id' field.
    Returns a list of textual descriptions of what's changed:
      - Event added
      - Event removed
      - Event changed (with old vs new)
    """
    changes = []
    old_dict = {e["id"]: e for e in old_events}
    new_dict = {e["id"]: e for e in new_events}
    old_ids = set(old_dict.keys())
    new_ids = set(new_dict.keys())

    # find added
    for eid in new_ids - old_ids:
        changes.append(f"Event added: {format_event(new_dict[eid])}")

    # find removed
    for eid in old_ids - new_ids:
        changes.append(f"Event removed: {format_event(old_dict[eid])}")

    # find changed
    for eid in old_ids & new_ids:
        if extract_comparable_fields(old_dict[eid]) != extract_comparable_fields(new_dict[eid]):
            old_str = format_event(old_dict[eid])
            new_str = format_event(new_dict[eid])
            changes.append(
                "Event changed:\n"
                f"OLD: {old_str}\nNEW: {new_str}"
            )
    return changes


# 7) --- Utility for Presenting an Event ---
def format_event(event: dict) -> str:
    """
    Returns a user-facing text describing a single event: 
    Title, start/end time, location if present.
    """
    title = event.get("summary", "No Title")

    # Acquire start
    start_val = event["start"].get("dateTime") or event["start"].get("date") or ""
    # Acquire end
    end_val   = event["end"].get("dateTime") or event["end"].get("date") or ""
    location  = event.get("location", "")

    # Convert if it has time
    if "T" in start_val:
        start_dt = datetime.fromisoformat(start_val.replace("Z", "+00:00")).astimezone(tz.tzlocal())
        start_str = start_dt.strftime("%Y-%m-%d %H:%M")
    else:
        start_str = start_val

    if "T" in end_val:
        end_dt = datetime.fromisoformat(end_val.replace("Z", "+00:00")).astimezone(tz.tzlocal())
        end_str = end_dt.strftime("%Y-%m-%d %H:%M")
    else:
        end_str = end_val

    if location:
        return f"- {title} ({start_str} to {end_str}, @ {location})"
    else:
        return f"- {title} ({start_str} to {end_str})"


# 8) --- Optional: Generating the UwU Greeting Based on a List of Events ---
def build_uwu_greeting_for_day(events: list[dict]):
    """
    Produces a cringe catgirl greeting plus a generated image,
    based on the entire list of events. 
    (If you want to focus on today's events only, that can be handled elsewhere.)
    """
    # Generate a text greeting
    event_titles = [e.get("summary", "mysterious event~") for e in events]
    greeting_text = generate_greeting(event_titles)

    # Generate an image prompt and fetch the image
    prompt = generate_image_prompt(event_titles)
    image_path = generate_image(prompt)

    return greeting_text, image_path


# 9) --- Optional Helper for Color Tagging (for Embeds, etc.) ---
def get_color_for_tag(tag: str) -> int:
    """
    If you still want color-coded tags, e.g. in Discord Embeds.
    Adjust as you see fit, or remove if you don't need it.
    """
    if tag == "T":
        return 0x3498db  # Blue
    elif tag == "A":
        return 0xe67e22  # Orange
    elif tag == "B":
        return 0x9b59b6  # Purple
    return 0x95a5a6     # Default gray
