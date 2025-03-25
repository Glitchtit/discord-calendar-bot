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

DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")
SERVICE_ACCOUNT_FILE = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
SCOPES = ["https://www.googleapis.com/auth/calendar"]
EVENTS_FILE = os.environ.get("EVENTS_FILE", "events.json")

credentials = service_account.Credentials.from_service_account_file(
    SERVICE_ACCOUNT_FILE, scopes=SCOPES
)
service = build("calendar", "v3", credentials=credentials)

# 1. CALENDAR DISCOVERY

def parse_calendar_sources():
    sources = os.environ.get("CALENDAR_SOURCES", "")
    parsed = []
    for entry in sources.split(","):
        entry = entry.strip()
        if entry.startswith("google:") or entry.startswith("ics:"):
            prefix, rest = entry.split(":", 1)
            # Split on last colon to separate optional custom name
            if ":" in rest:
                id_or_url, custom_name = rest.rsplit(":", 1)
                parsed.append((prefix, id_or_url.strip(), custom_name.strip()))
            else:
                parsed.append((prefix, rest.strip(), None))
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

    color = int(hashlib.md5(calendar_id.encode()).hexdigest()[:6], 16)
    return {"type": "google", "id": calendar_id, "name": name, "color": color}

def fetch_ics_calendar_metadata(url):
    name = url.split("/")[-1].split("?")[0] or "ICS Calendar"
    color = int(hashlib.md5(url.encode()).hexdigest()[:6], 16)
    return {"type": "ics", "id": url, "name": name, "color": color}

def load_calendar_sources():
    calendars = {}
    for ctype, cid, custom_name in parse_calendar_sources():
        if ctype == "google":
            meta = fetch_google_calendar_metadata(cid)
        elif ctype == "ics":
            meta = fetch_ics_calendar_metadata(cid)

        if custom_name:
            meta["name"] = custom_name

        calendars[cid] = meta
    return calendars


CALENDARS = load_calendar_sources()

# 2. LOADING / SAVING EVENTS

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


# 3. DISCORD EMBEDS + FORMATTING

def post_embed_to_discord(title: str, description: str, color: int = 5814783):
    if not DISCORD_WEBHOOK_URL:
        print("[DEBUG] No DISCORD_WEBHOOK_URL set.")
        return

    payload = {
        "embeds": [
            {
                "title": title,
                "description": description,
                "color": color
            }
        ]
    }

    resp = requests.post(DISCORD_WEBHOOK_URL, json=payload)
    if resp.status_code not in [200, 204]:
        print(f"[DEBUG] Discord post failed: {resp.status_code} {resp.text}")
    else:
        print("[DEBUG] Discord post successful.")

def format_event(event) -> str:
    start = event["start"].get("dateTime", event["start"].get("date"))
    end   = event["end"].get("dateTime", event["end"].get("date"))
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

    if location:
        return f"- {title} ({start_str} to {end_str}, at {location})"
    else:
        return f"- {title} ({start_str} to {end_str})"

# 4. FETCH EVENTS

def get_google_events(start_date, end_date, calendar_id):
    start_utc = start_date.isoformat() + "T00:00:00Z"
    end_utc   = end_date.isoformat() + "T23:59:59Z"

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
        response.encoding = 'utf-8'  # säkerställ rätt teckenkodning
        cal = ICS_Calendar(response.text)
        events = []
        for e in cal.events:
            if e.begin.date() >= start_date and e.begin.date() <= end_date:
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

# 5. DETECT CHANGES

def extract_comparable_fields(event):
    start = event["start"].get("dateTime", event["start"].get("date"))
    end = event["end"].get("dateTime", event["end"].get("date"))
    summary = event.get("summary", "")
    location = event.get("location", "")
    description = event.get("description", "")
    return (start, end, summary, location, description)

def detect_changes(old_events, new_events):
    changes = []
    old_dict = {e["id"]: e for e in old_events}
    new_dict = {e["id"]: e for e in new_events}
    old_ids = set(old_dict.keys())
    new_ids = set(new_dict.keys())

    for eid in new_ids - old_ids:
        changes.append(f"Event added: {format_event(new_dict[eid])}")

    for eid in old_ids - new_ids:
        changes.append(f"Event removed: {format_event(old_dict[eid])}")

    for eid in old_ids & new_ids:
        if extract_comparable_fields(old_dict[eid]) != extract_comparable_fields(new_dict[eid]):
            changes.append(
                f"Event changed:\nOLD: {format_event(old_dict[eid])}\nNEW: {format_event(new_dict[eid])}"
            )
    return changes

# 6. DAILY / WEEKLY POSTING

def post_summary_for_date(start_date, end_date, key_prefix, label):
    for cid, meta in CALENDARS.items():
        key = f"{key_prefix}_{meta['name'].replace(' ', '_')}_{start_date}"
        all_data = load_previous_events()
        old_events = all_data.get(key, [])
        new_events = get_events(meta, start_date, end_date)

        changes = detect_changes(old_events, new_events)
        if changes:
            post_embed_to_discord(f"Changes Detected for: {meta['name']}", "\n".join(changes), meta["color"])

        if new_events:
            lines = [format_event(e) for e in new_events]
            post_embed_to_discord(f"{label} for: {meta['name']}", "\n".join(lines), meta["color"])
        else:
            print(f"[DEBUG] No events for {meta['name']} during {label.lower()}. No message sent.")


        save_current_events_for_key(key, new_events)

def post_todays_happenings():
    today = datetime.now(tz=tz.tzlocal()).date()
    post_summary_for_date(today, today, "DAILY", "Today’s Happenings")

def post_weeks_happenings():
    now = datetime.now(tz=tz.tzlocal()).date()
    monday = now - timedelta(days=now.weekday())
    end = monday + timedelta(days=6)
    post_summary_for_date(monday, end, "WEEK", "This Week’s Happenings")

def check_for_changes():
    print("[DEBUG] check_for_changes() called.")
    today = datetime.now(tz=tz.tzlocal()).date()
    monday = today - timedelta(days=today.weekday())
    end = monday + timedelta(days=6)
    now = datetime.now(tz=tz.tzlocal())
    scheduled_weekly_time = now.replace(hour=8, minute=1, second=0, microsecond=0)
    delta = abs((now - scheduled_weekly_time).total_seconds())

    for cid, meta in CALENDARS.items():
        daily_key = f"DAILY_{meta['name'].replace(' ', '_')}_{today}"
        weekly_key = f"WEEK_{meta['name'].replace(' ', '_')}_{monday}"

        all_data = load_previous_events()
        old_daily = all_data.get(daily_key, [])
        old_week = all_data.get(weekly_key, [])

        new_daily = get_events(meta, today, today)
        new_week = get_events(meta, monday, end)

        daily_changes = detect_changes(old_daily, new_daily)
        weekly_changes = detect_changes(old_week, new_week)

        # Undvik post nära veckopost-tid
        if weekly_changes and delta > 180:  # 3 minuter = 180 sekunder
            post_embed_to_discord(f"Changes Detected for: {meta['name']} (Today)", "\n".join(weekly_changes), meta["color"])
            save_current_events_for_key(weekly_key, new_week)
        else:
            if weekly_changes:
                print(f"[DEBUG] Suppressed weekly change post for {meta['name']} due to timing (±3 min).")
                save_current_events_for_key(weekly_key, new_week)


    print("[DEBUG] check_for_changes() finished.")

# 7. SCHEDULE
schedule.every().day.at("08:00").do(post_todays_happenings)
schedule.every().monday.at("08:01").do(post_weeks_happenings)

if __name__ == "__main__":
    print("[DEBUG] Bot started. Immediately posting today's and this week's happenings.")
    post_todays_happenings()
    post_weeks_happenings()

    print("[DEBUG] Entering schedule loop. Checking for changes every 20 seconds.")
    while True:
        schedule.run_pending()
        check_for_changes()
        time.sleep(20)