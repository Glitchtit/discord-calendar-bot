# ╔════════════════════════════════════════════════════════════════════════════╗
# ║                       DISCORD MESSAGE FORMATTERS                           ║
# ║ Utilities for formatting calendar events and agendas into Discord Markdown.║
# ║ Includes functions for daily, weekly, and single-day agenda messages.      ║
# ╚════════════════════════════════════════════════════════════════════════════╝

# Standard library imports
from datetime import datetime, date
from typing import Dict, List, Any, Optional
import hashlib

# Local application imports
# (No local imports in this file)

# ╔════════════════════════════════════════════════════════════════════════════╗
# ║ HELPER FUNCTIONS                                                           ║
# ╚════════════════════════════════════════════════════════════════════════════╝

# --- get_calendar_color_emoji ---
# Generates a consistent colored square emoji based on a calendar name hash.
# Used for visually distinguishing calendars in messages.
# Args:
#     calendar_name: The name of the calendar.
# Returns: A string containing a colored square emoji.
def get_calendar_color_emoji(calendar_name: str) -> str:
    color_emojis = ['🟦', '🟥', '🟨', '🟩', '🟪', '🟧', '🟫', '⬛', '⬜']
    hash_value = int(hashlib.md5(calendar_name.encode()).hexdigest(), 16)
    return color_emojis[hash_value % len(color_emojis)]

# --- format_event_markdown ---
# Formats a single event dictionary into a Discord Markdown string.
# Includes title, time, location (optional), and description (truncated).
# Args:
#     event: The event dictionary (expected keys: summary, start, end, location, description).
#     calendar_emoji: Optional emoji string to prefix the event line.
# Returns: A formatted string representing the event for Discord.
def format_event_markdown(event: Dict[str, Any], calendar_emoji: Optional[str] = None) -> str:
    title = event.get("summary", "Untitled Event")
    location = event.get("location", "")
    description = event.get("description", "")
    # Time formatting
    start = event.get("start", {})
    end = event.get("end", {})
    start_dt = start.get("dateTime") or start.get("date")
    end_dt = end.get("dateTime") or end.get("date")
    if start_dt and 'T' in start_dt:
        try:
            start_obj = datetime.fromisoformat(start_dt.replace('Z', '+00:00'))
            start_str = start_obj.strftime('%H:%M')
        except Exception:
            start_str = "?"
    else:
        start_str = "All day"
    if end_dt and 'T' in end_dt:
        try:
            end_obj = datetime.fromisoformat(end_dt.replace('Z', '+00:00'))
            end_str = end_obj.strftime('%H:%M')
        except Exception:
            end_str = ""
    else:
        end_str = ""
    time_str = f"`{start_str}–{end_str}`" if end_str else f"`{start_str}`"
    # Compose event line
    prefix = f"{calendar_emoji} " if calendar_emoji else ""
    line = f"• {prefix}**{title}** {time_str}"
    if location:
        line += f"\n  📍 {location}"
    if description:
        short_desc = description[:100] + ("..." if len(description) > 100 else "")
        line += f"\n  _{short_desc}_"
    return line

# --- format_calendar_legend ---
# Creates a Markdown legend mapping calendar names to their color emojis.
# Only generates a legend if there are 2 or more calendars.
# Args:
#     calendar_names: A list of calendar names.
# Returns: A list of strings representing the legend lines, or an empty list.
def format_calendar_legend(calendar_names: List[str]) -> List[str]:
    if len(calendar_names) < 2:
        return []
    legend = ["**📊 Calendar Legend**"]
    for name in sorted(calendar_names):
        legend.append(f"{get_calendar_color_emoji(name)} {name}")
    return legend + [""]

# ╔════════════════════════════════════════════════════════════════════════════╗
# ║ AGENDA MESSAGE FORMATTERS                                                  ║
# ╚════════════════════════════════════════════════════════════════════════════╝

# --- format_daily_message ---
# Formats a daily agenda message for a user or public channel.
# Includes a header, total event count, optional legend, and events grouped by calendar.
# Args:
#     user_id: The Discord user ID (or "1" for public channel).
#     events_by_calendar: Dict mapping calendar names to lists of event dicts.
#     day: The date for which the agenda is being generated.
#     is_public: Boolean indicating if the message is for a public channel.
# Returns: A formatted multi-line string for the daily agenda message.
def format_daily_message(user_id: str, events_by_calendar: Dict[str, List[Dict[str, Any]]], day: date, is_public: bool = False) -> str:
    today_str = day.strftime('%A, %B %d, %Y')
    total_events = sum(len(ev) for ev in events_by_calendar.values())
    user_mention = "everyone" if user_id == "1" and is_public else f"<@{user_id}>"
    header = f"# 📅 {user_mention}'s Events • {today_str}\n"
    lines = [header, f"**Total events:** `{total_events}`\n"]
    if not events_by_calendar:
        lines.append("> ⚠️ *No events scheduled for today.*")
        return "\n".join(lines)
    # Legend
    lines += format_calendar_legend(list(events_by_calendar.keys()))
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━")
    # Events by calendar
    for cal_name in sorted(events_by_calendar.keys()):
        events = events_by_calendar[cal_name]
        if not events:
            continue
        emoji = get_calendar_color_emoji(cal_name)
        lines.append(f"\n## {emoji} {cal_name}")
        for event in sorted(events, key=lambda e: e["start"].get("dateTime", e["start"].get("date", ""))):
            lines.append(format_event_markdown(event, emoji))
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━")
    return "\n".join(lines)

# --- format_weekly_message ---
# Formats a weekly agenda message for a user.
# Includes a header, total event count, optional legend, and events grouped by day.
# Args:
#     user_id: The Discord user ID.
#     events_by_day: Dict mapping dates to lists of event dicts for the week.
#     start_day: The starting date of the week (usually a Monday).
# Returns: A formatted multi-line string for the weekly agenda message.
def format_weekly_message(user_id: str, events_by_day: Dict[date, List[Dict[str, Any]]], start_day: date) -> str:
    week_of = start_day.strftime('%B %d, %Y')
    total_events = sum(len(ev) for ev in events_by_day.values())
    header = f"# 📆 <@{user_id}>'s Weekly Schedule • Week of {week_of}\n"
    lines = [header, f"**Total events:** `{total_events}`\n"]
    # Collect all calendar names for legend
    calendar_names = set()
    for events in events_by_day.values():
        for event in events:
            calendar_names.add(event.get("calendar_name", event.get("calendar_id", "unknown")))
    lines += format_calendar_legend(list(calendar_names))
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━")
    # Events by day
    for day, events in sorted(events_by_day.items()):
        day_str = day.strftime('%A, %B %d')
        lines.append(f"\n## {day_str}")
        if not events:
            lines.append("> *No events scheduled*\n")
            continue
        for event in sorted(events, key=lambda e: e["start"].get("dateTime", e["start"].get("date", ""))):
            emoji = get_calendar_color_emoji(event.get("calendar_name", event.get("calendar_id", "unknown")))
            lines.append(format_event_markdown(event, emoji))
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━")
    return "\n".join(lines)

# --- format_agenda_message ---
# Formats a single-day agenda message, often used for the /agenda command.
# Similar to daily message but can have a custom source name.
# Args:
#     user_id: The Discord user ID.
#     events_by_day: Dict mapping the target date to a list of event dicts.
#     target_date: The specific date for the agenda.
#     source_name: Optional name to display in the header (e.g., calendar name).
# Returns: A formatted multi-line string for the single-day agenda.
def format_agenda_message(user_id: str, events_by_day: Dict[date, List[Dict[str, Any]]], target_date: date, source_name: Optional[str] = None) -> str:
    date_str = target_date.strftime('%A, %B %d, %Y')
    total_events = sum(len(ev) for ev in events_by_day.values())
    header = f"# 🗒️ {source_name or f'<@{user_id}>'}'s Agenda • {date_str}\n"
    lines = [header, f"**Total events:** `{total_events}`\n"]
    # Collect all calendar names for legend
    calendar_names = set()
    for events in events_by_day.values():
        for event in events:
            calendar_names.add(event.get("calendar_name", event.get("calendar_id", "unknown")))
    lines += format_calendar_legend(list(calendar_names))
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━")
    # Events for the day
    for day, events in sorted(events_by_day.items()):
        if not events:
            lines.append("> *No events scheduled*\n")
            continue
        for event in sorted(events, key=lambda e: e["start"].get("dateTime", e["start"].get("date", ""))):
            emoji = get_calendar_color_emoji(event.get("calendar_name", event.get("calendar_id", "unknown")))
            lines.append(format_event_markdown(event, emoji))
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━")
    return "\n".join(lines)
