from datetime import datetime, timedelta, date
from dateutil import tz


# ╔════════════════════════════════════════════════════════════════════╗
# ║ 📅 get_today                                                       ║
# ║ Returns the current date in the local timezone                    ║
# ╚════════════════════════════════════════════════════════════════════╝
def get_today() -> date:
    return datetime.now(tz=tz.tzlocal()).date()


# ╔════════════════════════════════════════════════════════════════════╗
# ║ 📆 get_monday_of_week                                              ║
# ║ Returns the Monday of the given date's week                        ║
# ╚════════════════════════════════════════════════════════════════════╝
def get_monday_of_week(day: date) -> date:
    return day - timedelta(days=day.weekday())


# ╔════════════════════════════════════════════════════════════════════╗
# ║ 🔤 emoji_for_event                                                 ║
# ║ Attempts to guess an emoji based on event title                    ║
# ╚════════════════════════════════════════════════════════════════════╝
def emoji_for_event(title: str) -> str:
    title = title.lower()
    if "class" in title or "lecture" in title or "em" in title or "ia" in title:
        return "📚"
    if "meeting" in title:
        return "📞"
    if "lunch" in title:
        return "🥪"
    if "dinner" in title or "banquet" in title:
        return "🍽️"
    if "party" in title:
        return "🎉"
    if "exam" in title or "test" in title:
        return "📝"
    if "appointment" in title:
        return "📅"
    return "•"


# ╔════════════════════════════════════════════════════════════════════╗
# ║ 📝 format_event                                                    ║
# ║ Converts an event dictionary into a stylized, readable string     ║
# ╚════════════════════════════════════════════════════════════════════╝
def format_event(event: dict) -> str:
    start = event["start"].get("dateTime", event["start"].get("date"))
    end = event["end"].get("dateTime", event["end"].get("date"))
    title = event.get("summary", "Untitled")
    location = event.get("location", "")
    emoji = emoji_for_event(title)

    if "T" in start:
        start_dt = datetime.fromisoformat(start.replace("Z", "+00:00")).astimezone(tz.tzlocal())
        start_str = start_dt.strftime("%H:%M")
    else:
        start_str = "All Day"

    if "T" in end:
        end_dt = datetime.fromisoformat(end.replace("Z", "+00:00")).astimezone(tz.tzlocal())
        end_str = end_dt.strftime("%H:%M")
    else:
        end_str = ""

    time_range = f"{start_str}–{end_str}" if end_str else start_str
    location_str = f" *({location})*" if location else ""

    return f"{emoji} **{title}** `{time_range}`{location_str}"


# ╔════════════════════════════════════════════════════════════════════╗
# ║ 📅 is_in_current_week                                              ║
# ║ Determines if an event occurs within the current week             ║
# ╚════════════════════════════════════════════════════════════════════╝
def is_in_current_week(event: dict, reference: date = None) -> bool:
    reference = reference or get_today()
    monday = get_monday_of_week(reference)
    week_range = {monday + timedelta(days=i) for i in range(7)}
    start_str = event["start"].get("dateTime", event["start"].get("date"))
    dt = datetime.fromisoformat(start_str.replace("Z", "+00:00")) if "T" in start_str else datetime.fromisoformat(start_str)
    return dt.date() in week_range


# ╔════════════════════════════════════════════════════════════════════╗
# ║ 🔍 resolve_input_to_tags                                           ║
# ║ Maps user-friendly input strings to internal calendar tags        ║
# ╚════════════════════════════════════════════════════════════════════╝
def resolve_input_to_tags(input_str: str, tag_names: dict, grouped_calendars: dict) -> list[str]:
    requested = [s.strip().lower() for s in input_str.split(",") if s.strip()]
    matched = set()
    for item in requested:
        if item.upper() in grouped_calendars:
            matched.add(item.upper())
        else:
            for tag, name in tag_names.items():
                if name.lower() == item:
                    matched.add(tag)
    return list(matched)
