from datetime import datetime, date
from typing import Dict, List, Any, Optional
import hashlib

def get_calendar_color_emoji(calendar_name: str) -> str:
    """Generate a consistent colored square emoji for a calendar based on its name."""
    # Available color emoji squares
    color_emojis = ['🟦', '🟥', '🟨', '🟩', '🟪', '🟧', '🟫', '⬛', '⬜']
    
    # Hash the calendar name to get a consistent index
    hash_value = int(hashlib.md5(calendar_name.encode()).hexdigest(), 16)
    index = hash_value % len(color_emojis)
    
    return color_emojis[index]

def format_event_markdown(event: Dict[str, Any], calendar_emoji: str = None) -> str:
    """Format a single event in Markdown."""
    # Get event details
    event_name = event.get("summary", "Untitled Event")
    location = event.get("location", "")
    description = event.get("description", "")
    
    # Format event time
    start_dt = event["start"].get("dateTime")
    end_dt = event["end"].get("dateTime")
    
    if start_dt and end_dt:  # Has specific times
        start = datetime.fromisoformat(start_dt.replace('Z', '+00:00'))
        end = datetime.fromisoformat(end_dt.replace('Z', '+00:00'))
        time_str = f"`{start.strftime('%H:%M')}–{end.strftime('%H:%M')}`"
    else:  # All-day event
        time_str = "`All day`"
    
    # Start with the color emoji (if provided) and the event name and time
    event_prefix = calendar_emoji + " " if calendar_emoji else ""
    event_line = f"• {event_prefix}**{event_name}** {time_str}"
    
    # Add location if available
    if location:
        event_line += f"\n  📍 {location}"
    
    # Add a short preview of description if available
    if description:
        # Limit description to ~100 chars for preview
        short_desc = description[:97] + "..." if len(description) > 100 else description
        event_line += f"\n  _{short_desc}_"
    
    return event_line

# --- REFACTORED FORMATTERS FOR OPTIMIZED UX ---
def format_daily_message(user_id: str, events_by_calendar: Dict[str, List[Dict[str, Any]]], 
                         day: date, is_public: bool = False) -> str:
    today_str = day.strftime('%A, %B %d')
    total_events = sum(len(events) for events in events_by_calendar.values())
    if is_public:
        if user_id == "1":
            header = f"# 📅 Events for Everyone • {today_str}\n"
        else:
            header = f"# 📅 Events for <@{user_id}> • {today_str}\n"
    else:
        header = f"# 📅 Your Events • {today_str}\n"
    message = [header]
    message.append(f"**Total events:** `{total_events}`\n")
    if not events_by_calendar:
        message.append("> ⚠️ *No events scheduled for today.*")
        return "\n".join(message)
    # Calendar legend
    message.append("## 📊 Calendar Legend")
    for calendar_name in sorted(events_by_calendar.keys()):
        emoji = get_calendar_color_emoji(calendar_name)
        message.append(f"{emoji} {calendar_name}")
    message.append("\n━━━━━━━━━━━━━━━━━━━━━━━━━━\n")
    # Events by calendar
    message.append("## 🗒️ Today's Events")
    for calendar_name, events in sorted(events_by_calendar.items()):
        if events:
            calendar_emoji = get_calendar_color_emoji(calendar_name)
            message.append(f"**{calendar_emoji} {calendar_name}**")
            sorted_events = sorted(events, key=lambda e: e["start"].get("dateTime", e["start"].get("date", "")))
            for event in sorted_events:
                message.append(format_event_markdown(event, calendar_emoji))
            message.append("")
    message.append("━━━━━━━━━━━━━━━━━━━━━━━━━━")
    return "\n".join(message)

def format_weekly_message(user_id: str, events_by_day: Dict[date, List[Dict[str, Any]]], 
                         start_day: date) -> str:
    week_of_str = start_day.strftime('%B %d')
    total_events = sum(len(events) for events in events_by_day.values())
    header = f"# 📆 Weekly Schedule • Week of {week_of_str}\n"
    message = [header]
    message.append(f"**Total events:** `{total_events}`\n")
    if not events_by_day:
        message.append("> ⚠️ *No events scheduled for this week.*")
        return "\n".join(message)
    calendar_colors = {}
    for day_events in events_by_day.values():
        for event in day_events:
            calendar_id = event.get("calendar_id", "unknown")
            calendar_name = event.get("calendar_name", calendar_id)
            if calendar_name not in calendar_colors:
                calendar_colors[calendar_name] = get_calendar_color_emoji(calendar_name)
    if len(calendar_colors) > 1:
        message.append("## 📊 Calendar Legend")
        for cal_name, emoji in sorted(calendar_colors.items()):
            message.append(f"{emoji} {cal_name}")
        message.append("")
    message.append("━━━━━━━━━━━━━━━━━━━━━━━━━━\n")
    for day, events in sorted(events_by_day.items()):
        day_str = day.strftime('%A, %B %d')
        message.append(f"### {day_str}")
        if not events:
            message.append("> *No events scheduled*\n")
            continue
        sorted_events = sorted(events, key=lambda e: e["start"].get("dateTime", e["start"].get("date", "")))
        for event in sorted_events:
            calendar_id = event.get("calendar_id", "unknown")
            calendar_name = event.get("calendar_name", calendar_id)
            emoji = calendar_colors.get(calendar_name, "")
            message.append(format_event_markdown(event, emoji))
        message.append("")
    message.append("━━━━━━━━━━━━━━━━━━━━━━━━━━")
    return "\n".join(message)

def format_agenda_message(user_id: str, events_by_day: Dict[date, List[Dict[str, Any]]], 
                         target_date: date, source_name: Optional[str] = None) -> str:
    date_str = target_date.strftime('%A, %B %d')
    total_events = sum(len(events) for events in events_by_day.values())
    if source_name:
        header = f"# 📅 {source_name} • {date_str}\n"
    else:
        header = f"# 📅 Your Agenda • {date_str}\n"
    message = [header]
    message.append(f"**Total events:** `{total_events}`\n")
    if not events_by_day:
        message.append("> ⚠️ *No events scheduled for this day.*")
        return "\n".join(message)
    calendar_colors = {}
    for day_events in events_by_day.values():
        for event in day_events:
            calendar_id = event.get("calendar_id", "unknown")
            calendar_name = event.get("calendar_name", calendar_id)
            if calendar_name not in calendar_colors:
                calendar_colors[calendar_name] = get_calendar_color_emoji(calendar_name)
    if len(calendar_colors) > 1:
        message.append("## 📊 Calendar Legend")
        for cal_name, emoji in sorted(calendar_colors.items()):
            message.append(f"{emoji} {cal_name}")
        message.append("")
    message.append("━━━━━━━━━━━━━━━━━━━━━━━━━━\n")
    for day, events in sorted(events_by_day.items()):
        if not events:
            message.append("> *No events scheduled*\n")
            continue
        sorted_events = sorted(events, key=lambda e: e["start"].get("dateTime", e["start"].get("date", "")))
        for event in sorted_events:
            calendar_id = event.get("calendar_id", "unknown")
            calendar_name = event.get("calendar_name", calendar_id)
            emoji = calendar_colors.get(calendar_name, "")
            message.append(format_event_markdown(event, emoji))
    message.append("━━━━━━━━━━━━━━━━━━━━━━━━━━")
    return "\n".join(message)
