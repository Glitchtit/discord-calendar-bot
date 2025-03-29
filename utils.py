from datetime import datetime, timedelta, date
from dateutil import tz


def get_today() -> date:
    """Return the current date in local timezone."""
    return datetime.now(tz=tz.tzlocal()).date()


def get_monday_of_week(day: date) -> date:
    """Return the Monday of the given date's week."""
    return day - timedelta(days=day.weekday())


def format_event(event: dict) -> str:
    """Return a readable event summary."""
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


def is_in_current_week(event: dict, reference: date = None) -> bool:
    """Return True if the event occurs within the current week."""
    reference = reference or get_today()
    monday = get_monday_of_week(reference)
    week_range = {monday + timedelta(days=i) for i in range(7)}
    start_str = event["start"].get("dateTime", event["start"].get("date"))
    dt = datetime.fromisoformat(start_str.replace("Z", "+00:00")) if "T" in start_str else datetime.fromisoformat(start_str)
    return dt.date() in week_range


def resolve_input_to_tags(input_str: str, tag_names: dict, grouped_calendars: dict) -> list[str]:
    """Convert user input (tag or name) to matching tag list."""
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
