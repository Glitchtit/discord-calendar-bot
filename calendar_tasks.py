import os
import json
import hashlib
import requests
from datetime import datetime, timezone
from dateutil import tz
from ics import Calendar as ICS_Calendar

from google.oauth2 import service_account
from googleapiclient.discovery import build

from ai import generate_greeting, generate_image_prompt, generate_image

SERVICE_ACCOUNT_FILE = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "service_account.json")
SCOPES = ["https://www.googleapis.com/auth/calendar"]
EVENTS_FILE = os.environ.get("EVENTS_FILE", "/data/events.json")

ALL_EVENTS_KEY = "ALL_EVENTS"

credentials = service_account.Credentials.from_service_account_file(
    SERVICE_ACCOUNT_FILE, scopes=SCOPES
)
service = build("calendar", "v3", credentials=credentials)


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
                cal_id_or_url, tag = rest.rsplit(":", 1)
                results.append((prefix, cal_id_or_url.strip(), tag.strip().upper()))
    return results


def fetch_google_calendar_metadata(calendar_id: str):
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
    name = url.split("/")[-1].split("?")[0] or "ICS Calendar"
    return {
        "type": "ics",
        "id": url,
        "name": name
    }


def load_calendar_sources():
    grouped = {}
    for ctype, cal_id_or_url, tag in parse_calendar_sources():
        if ctype == "google":
            meta = fetch_google_calendar_metadata(cal_id_or_url)
        elif ctype == "ics":
            meta = fetch_ics_calendar_metadata(cal_id_or_url)
        else:
            continue

        meta["tag"] = tag
        grouped.setdefault(tag, []).append(meta)
    return grouped


GROUPED_CALENDARS = load_calendar_sources()


def load_previous_events() -> dict:
    if os.path.exists(EVENTS_FILE):
        try:
            with open(EVENTS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError:
            pass
    return {}


def save_current_events_for_key(key: str, events: list):
    all_data = load_previous_events()
    all_data[key] = events
    with open(EVENTS_FILE, "w", encoding="utf-8") as f:
        json.dump(all_data, f, ensure_ascii=False, indent=2)


def get_all_calendar_events() -> list:
    """
    Loads events starting from 'now' (UTC) forward. 
    This discards past events.
    For Google, we use timeMin in the API call.
    For ICS, we parse everything, but only keep events ending in the future.
    """
    now_utc = datetime.utcnow().replace(tzinfo=timezone.utc)
    now_iso = now_utc.isoformat()

    sources = []
    for cals_list in GROUPED_CALENDARS.values():
        sources.extend(cals_list)

    all_events = []
    for meta in sources:
        if meta["type"] == "google":
            try:
                # Get future events from now forward, ignoring historical ones
                items = service.events().list(
                    calendarId=meta["id"],
                    timeMin=now_iso,
                    maxResults=2500,
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

                # Filter ICS events to keep only those that end in the future
                # If you'd rather keep an event that started in the past but ends later,
                # you can check e.end > now_utc. Or if you want strictly upcoming events,
                # you can compare e.begin to now_utc. Adjust logic to your needs:
                for e in ics_cal.events:
                    if e.end and e.end >= now_utc:
                        # Build an event record
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

    def sort_key(evt):
        # prefer dateTime if it exists, else date
        maybe_start = evt["start"].get("dateTime", evt["start"].get("date", "2099-12-31"))
        return maybe_start
    all_events.sort(key=sort_key)

    return all_events


def extract_comparable_fields(event: dict):
    start = event["start"].get("dateTime", event["start"].get("date", ""))
    end = event["end"].get("dateTime", event["end"].get("date", ""))
    summary = event.get("summary", "")
    location = event.get("location", "")
    description = event.get("description", "")
    return (start, end, summary, location, description)


def detect_changes(old_events: list, new_events: list) -> list[str]:
    changes = []
    old_dict = {e["id"]: e for e in old_events}
    new_dict = {e["id"]: e for e in new_events}
    old_ids = set(old_dict.keys())
    new_ids = set(new_dict.keys())

    # added
    for eid in new_ids - old_ids:
        changes.append(f"Event added: {format_event(new_dict[eid])}")

    # removed
    for eid in old_ids - new_ids:
        changes.append(f"Event removed: {format_event(old_dict[eid])}")

    # changed
    for eid in old_ids & new_ids:
        if extract_comparable_fields(old_dict[eid]) != extract_comparable_fields(new_dict[eid]):
            old_str = format_event(old_dict[eid])
            new_str = format_event(new_dict[eid])
            changes.append(
                "Event changed:\n"
                f"OLD: {old_str}\nNEW: {new_str}"
            )
    return changes


def format_event(event: dict) -> str:
    title = event.get("summary", "No Title")
    start_val = event["start"].get("dateTime") or event["start"].get("date") or ""
    end_val   = event["end"].get("dateTime") or event["end"].get("date") or ""
    location  = event.get("location", "")

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


def build_uwu_greeting_for_day(events: list[dict]):
    event_titles = [e.get("summary", "mysterious event~") for e in events]
    greeting_text = generate_greeting(event_titles)
    prompt = generate_image_prompt(event_titles)
    image_path = generate_image(prompt)
    return greeting_text, image_path


def get_color_for_tag(tag: str) -> int:
    if tag == "T":
        return 0x3498db  # Blue
    elif tag == "A":
        return 0xe67e22  # Orange
    elif tag == "B":
        return 0x9b59b6  # Purple
    return 0x95a5a6     # Default gray
