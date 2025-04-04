from datetime import date, datetime, timedelta
from events import GROUPED_CALENDARS
from zoneinfo import ZoneInfo

# ╔════════════════════════════════════════════════════════════════════╗
# 📆 Get Today (Local Date)
# ╚════════════════════════════════════════════════════════════════════╝
def get_today() -> date:
    return datetime.now().date()

# ╔════════════════════════════════════════════════════════════════════╗
# 🗓️ Get Monday of the Current Week
# ╚════════════════════════════════════════════════════════════════════╝
def get_monday_of_week(ref: date = None) -> date:
    ref = ref or get_today()
    return ref - timedelta(days=ref.weekday())

# ╔════════════════════════════════════════════════════════════════════╗
# 🧠 Check if Event is in Current Week
# ╚════════════════════════════════════════════════════════════════════╝
def is_in_current_week(event_start: str) -> bool:
    try:
        dt = datetime.fromisoformat(event_start.replace("Z", "+00:00"))
        today = get_today()
        monday = get_monday_of_week(today)
        return monday <= dt.date() <= monday + timedelta(days=6)
    except Exception:
        return False

# ╔════════════════════════════════════════════════════════════════════╗
# 🧠 Resolve Timezone from TZID
# ╚════════════════════════════════════════════════════════════════════╝
def resolve_tz(tzid: str):
    try:
        return ZoneInfo(tzid)
    except Exception:
        return ZoneInfo("UTC")

# ╔════════════════════════════════════════════════════════════════════╗
# ✨ Format Event for Discord Embed
# ╚════════════════════════════════════════════════════════════════════╝
def format_event(event: dict) -> str:
    summary = event.get("summary", "Untitled")
    location = event.get("location", "")
    is_all_day = event.get("allDay", False)
    start = event["start"].get("dateTime", event["start"].get("date"))
    end = event["end"].get("dateTime", event["end"].get("date"))

    # Extract time portion
    if not is_all_day and "T" in start:
        start_time = datetime.fromisoformat(start.replace("Z", "+00:00")).strftime("%H:%M")
        end_time = datetime.fromisoformat(end.replace("Z", "+00:00")).strftime("%H:%M")
        time_str = f"🕒 {start_time}–{end_time}"
    else:
        time_str = "📌 All day"

    loc_str = f"📍 {location}" if location else ""
    return f"**{summary}**\n{time_str} {loc_str}".strip()

# ╔════════════════════════════════════════════════════════════════════╗
# 🔤 Resolve Slash Command Input to Valid Tags
# ╚════════════════════════════════════════════════════════════════════╝
def resolve_input_to_tags(value: str) -> list[str]:
    value = value.strip().upper()
    if value in ("*", "ALL", "BOTH"):
        return list(GROUPED_CALENDARS.keys())
    if value in GROUPED_CALENDARS:
        return [value]
    return []
