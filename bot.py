import os
import requests
import schedule
import time
import json
import hashlib
from datetime import datetime, timedelta
from dateutil import tz
from ics import Calendar as ICS_Calendar
from google.oauth2 import service_account
from googleapiclient.discovery import build
from ai import post_greeting_to_discord

DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")
SERVICE_ACCOUNT_FILE = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
SCOPES = ["https://www.googleapis.com/auth/calendar"]
EVENTS_FILE = "/data/events.json"

credentials = service_account.Credentials.from_service_account_file(
    SERVICE_ACCOUNT_FILE, scopes=SCOPES
)
service = build("calendar", "v3", credentials=credentials)

def get_color_for_tag(tag):
    return {
        "T": 0x3498db,  # Blue (Thomas)
        "A": 0xe67e22,  # Orange (Anniina)
        "B": 0x9b59b6,  # Purple (Both)
    }.get(tag, 0x95a5a6)  # Default gray

def parse_calendar_sources():
    sources = os.environ.get("CALENDAR_SOURCES", "")
    parsed = []
    for entry in sources.split(","):
        entry = entry.strip()
        if entry.startswith("google:") or entry.startswith("ics:"):
            prefix, rest = entry.split(":", 1)
            if ":" in rest:
                id_or_url, tag = rest.rsplit(":", 1)
                parsed.append((prefix, id_or_url.strip(), tag.strip().upper()))
    return parsed

def fetch_google_calendar_metadata(calendar_id):
    try:
        service.calendarList().insert(body={"id": calendar_id}).execute()
    except Exception as e:
        if "Already Exists" not in str(e):
            print(f"[WARNING] Couldn't subscribe to {calendar_id}: {e}")
    try:
        cal = service.calendarList().get(calendarId=calendar_id).execute()
        name = cal.get("summaryOverride") or cal.get("summary") or calendar_id
    except Exception as e:
        print(f"[WARNING] Couldn't get calendar metadata for {calendar_id}: {e}")
        name = calendar_id
    return {"type": "google", "id": calendar_id, "name": name}

def fetch_ics_calendar_metadata(url):
    name = url.split("/")[-1].split("?")[0] or "ICS Calendar"
    return {"type": "ics", "id": url, "name": name}

def load_calendar_sources():
    grouped = {"T": [], "A": [], "B": []}
    for ctype, cid, tag in parse_calendar_sources():
        meta = fetch_google_calendar_metadata(cid) if ctype == "google" else fetch_ics_calendar_metadata(cid)
        meta["tag"] = tag
        grouped.setdefault(tag, []).append(meta)
    return grouped

GROUPED_CALENDARS = load_calendar_sources()

def load_previous_events():
    if os.path.exists(EVENTS_FILE):
        with open(EVENTS_FILE, "r", encoding="utf-8") as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                pass
    return {}

def save_current_events_for_key(key, events):
    all_data = load_previous_events()
    all_data[key] = events
    with open(EVENTS_FILE, "w", encoding="utf-8") as f:
        json.dump(all_data, f, ensure_ascii=False)

def post_embed_to_discord(title: str, description: str, color: int = 5814783):
    if not DISCORD_WEBHOOK_URL:
        print("[DEBUG] No DISCORD_WEBHOOK_URL set.")
        return
    payload = {
        "embeds": [{
            "title": title,
            "description": description,
            "color": color
        }]
    }
    resp = requests.post(DISCORD_WEBHOOK_URL, json=payload)
    if resp.status_code not in [200, 204]:
        print(f"[DEBUG] Discord post failed: {resp.status_code} {resp.text}")
    else:
        print("[DEBUG] Discord post successful.")

def format_event(event) -> str:
    start = event["start"].get("dateTime", event["start"].get("date"))
    end = event["end"].get("dateTime", event["end"].get("date"))
    title = event.get("summary", "No Title")
    location = event.get("location", "")
    if "T" in start:
        start_dt = datetime.fromisoformat(start.replace("Z", "+00:00")).astimezone(tz.tzlocal())
        start_str = start_dt.strftime("%Y-%m-%d %H:%M")
    else:
        start_str = start
    if "T" in end:
        end_dt = datetime.fromisoformat(end.replace("Z", "+00:00")).astimezone(tz.tzlocal())
        end_str = end_dt.strftime("%Y-%m-%d %H:%M")
    else:
        end_str = end
    return f"- {title} ({start_str} to {end_str}" + (f", at {location})" if location else ")")

def get_google_events(start_date, end_date, calendar_id):
    start_utc = start_date.isoformat() + "T00:00:00Z"
    end_utc = end_date.isoformat() + "T23:59:59Z"
    result = service.events().list(
        calendarId=calendar_id,
        timeMin=start_utc,
        timeMax=end_utc,
        singleEvents=True,
        orderBy="startTime"
    ).execute()
    return result.get("items", [])

def get_ics_events(start_date, end_date, url):
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
        return events
    except Exception as e:
        print(f"[ERROR] Could not fetch or parse ICS calendar: {url} - {e}")
        return []

def get_events(source_meta, start_date, end_date):
    if source_meta["type"] == "google":
        return get_google_events(start_date, end_date, source_meta["id"])
    elif source_meta["type"] == "ics":
        return get_ics_events(start_date, end_date, source_meta["id"])
    return []

def extract_comparable_fields(event):
    return (
        event["start"].get("dateTime", event["start"].get("date")),
        event["end"].get("dateTime", event["end"].get("date")),
        event.get("summary", ""),
        event.get("location", ""),
        event.get("description", "")
    )

def detect_changes(old_events, new_events):
    changes = []
    old_dict = {e["id"]: e for e in old_events}
    new_dict = {e["id"]: e for e in new_events}
    for eid in new_dict.keys() - old_dict.keys():
        changes.append(f"Event added: {format_event(new_dict[eid])}")
    for eid in old_dict.keys() - new_dict.keys():
        changes.append(f"Event removed: {format_event(old_dict[eid])}")
    for eid in new_dict.keys() & old_dict.keys():
        if extract_comparable_fields(new_dict[eid]) != extract_comparable_fields(old_dict[eid]):
            changes.append(
                f"Event changed:\nOLD: {format_event(old_dict[eid])}\nNEW: {format_event(new_dict[eid])}"
            )
    return changes

def post_todays_happenings():
    today = datetime.now(tz=tz.tzlocal()).date()
    weekday_name = today.strftime("%A")
    all_events_for_greeting = []
    for tag, calendars in GROUPED_CALENDARS.items():
        all_events = []
        for meta in calendars:
            all_events += get_events(meta, today, today)
        if all_events:
            all_events.sort(key=lambda e: e["start"].get("dateTime", e["start"].get("date")))
            lines = [format_event(e) for e in all_events]
            person = "Thomas" if tag == "T" else "Anniina" if tag == "A" else "Both"
            post_embed_to_discord(
                f"Today’s Happenings – {weekday_name} for {person}",
                "\n".join(lines),
                get_color_for_tag(tag)
            )
            all_events_for_greeting += all_events
    post_greeting_to_discord(all_events_for_greeting)

def post_weeks_happenings():
    now = datetime.now(tz=tz.tzlocal()).date()
    monday = now - timedelta(days=now.weekday())
    end = monday + timedelta(days=6)
    for tag, calendars in GROUPED_CALENDARS.items():
        all_events = []
        for meta in calendars:
            all_events += get_events(meta, monday, end)
        if not all_events:
            continue
        events_by_day = {}
        for e in all_events:
            start_str = e["start"].get("dateTime", e["start"].get("date"))
            dt = datetime.fromisoformat(start_str.replace("Z", "+00:00")) if "T" in start_str else datetime.fromisoformat(start_str)
            day = dt.date()
            events_by_day.setdefault(day, []).append(e)
        lines = []
        for i in range(7):
            day = monday + timedelta(days=i)
            if day in events_by_day:
                lines.append(f"**{day.strftime('%A')}**")
                day_events = sorted(events_by_day[day], key=lambda e: e["start"].get("dateTime", e["start"].get("date")))
                lines.extend(format_event(e) for e in day_events)
                lines.append("")
        person = "Thomas" if tag == "T" else "Anniina" if tag == "A" else "Both"
        post_embed_to_discord(
            f"This Week’s Happenings for {person}",
            "\n".join(lines),
            get_color_for_tag(tag)
        )

def check_for_changes():
    today = datetime.now(tz=tz.tzlocal()).date()
    monday = today - timedelta(days=today.weekday())
    end = monday + timedelta(days=6)
    now = datetime.now(tz=tz.tzlocal())
    scheduled_time = now.replace(hour=8, minute=1, second=0, microsecond=0)
    delta = abs((now - scheduled_time).total_seconds())
    for tag, calendars in GROUPED_CALENDARS.items():
        key = f"WEEK_{tag}_{monday}"
        old_events = load_previous_events().get(key, [])
        new_events = []
        for meta in calendars:
            new_events += get_events(meta, monday, end)
        changes = detect_changes(old_events, new_events)
        if changes and delta > 180:
            post_embed_to_discord(
                f"Changes Detected – For {tag}",
                "\n".join(changes),
                get_color_for_tag(tag)
            )
            save_current_events_for_key(key, new_events)
        elif changes:
            print(f"[DEBUG] Suppressed weekly change post for {tag} due to timing (±3 min).")
            save_current_events_for_key(key, new_events)

# Schedule jobs
schedule.every().day.at("08:01").do(post_todays_happenings)
schedule.every().monday.at("08:00").do(post_weeks_happenings)

if __name__ == "__main__":
    print("[DEBUG] Bot started. Posting weekly + daily events now.")
    post_weeks_happenings()
    post_todays_happenings()
    print("[DEBUG] Entering schedule loop.")
    while True:
        schedule.run_pending()
        check_for_changes()
        time.sleep(20)
