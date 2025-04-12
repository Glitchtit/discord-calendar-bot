from datetime import datetime, date
from typing import Dict, List, Any, Optional

def format_event_markdown(event: Dict[str, Any]) -> str:
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
    
    # Start with the event name and time
    event_line = f"• **{event_name}** {time_str}"
    
    # Add location if available
    if location:
        event_line += f"\n  📍 {location}"
    
    # Add a short preview of description if available
    if description:
        # Limit description to ~100 chars for preview
        short_desc = description[:97] + "..." if len(description) > 100 else description
        event_line += f"\n  _{short_desc}_"
    
    return event_line

def format_daily_message(user_id: str, events_by_calendar: Dict[str, List[Dict[str, Any]]], 
                         day: date, is_public: bool = False) -> str:
    """Format daily events into a Markdown message."""
    today_str = day.strftime('%A, %B %d')
    
    # Create header with different styling based on whether it's public or personal
    if is_public:
        if user_id == "1":  # Server-wide calendar
            header = f"# 📅 Events for Everyone • {today_str}\n"
        else:
            header = f"# 📅 Events for <@{user_id}> • {today_str}\n"
    else:
        header = f"# 📅 Your Events • {today_str}\n"
    
    message = [header]
    
    # If no events, add a message
    if not events_by_calendar:
        message.append("*No events scheduled for today.*")
        return "\n".join(message)
    
    # Add events by calendar
    for calendar_name, events in sorted(events_by_calendar.items()):
        if events:
            message.append(f"\n## 📁 {calendar_name}")
            
            # Sort events by start time
            sorted_events = sorted(events, key=lambda e: e["start"].get("dateTime", e["start"].get("date", "")))
            
            for event in sorted_events:
                message.append(format_event_markdown(event))
    
    return "\n".join(message)

def format_weekly_message(user_id: str, events_by_day: Dict[date, List[Dict[str, Any]]], 
                         start_day: date) -> str:
    """Format weekly events into a Markdown message."""
    week_of_str = start_day.strftime('%B %d')
    
    header = f"# 📆 Weekly Schedule • Week of {week_of_str}\n"
    message = [header]
    
    # If no events, add a message
    if not events_by_day:
        message.append("*No events scheduled for this week.*")
        return "\n".join(message)
    
    # Add events by day
    for day, events in sorted(events_by_day.items()):
        day_str = day.strftime('%A, %B %d')
        message.append(f"\n## {day_str}")
        
        if not events:
            message.append("*No events scheduled*")
            continue
        
        # Sort events by start time
        sorted_events = sorted(events, key=lambda e: e["start"].get("dateTime", e["start"].get("date", "")))
        
        for event in sorted_events:
            message.append(format_event_markdown(event))
    
    return "\n".join(message)

def format_agenda_message(user_id: str, events_by_day: Dict[date, List[Dict[str, Any]]], 
                         target_date: date, source_name: Optional[str] = None) -> str:
    """Format agenda events into a Markdown message."""
    date_str = target_date.strftime('%A, %B %d')
    
    if source_name:
        header = f"# 📅 {source_name} • {date_str}\n"
    else:
        header = f"# 📅 Your Agenda • {date_str}\n"
    
    message = [header]
    
    # If no events, add a message
    if not events_by_day:
        message.append("*No events scheduled for this day.*")
        return "\n".join(message)
    
    # Add a separator
    message.append("```\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n```")
    
    # Add events by day (usually just one day for agenda)
    for day, events in sorted(events_by_day.items()):
        if not events:
            message.append("*No events scheduled*")
            continue
        
        # Sort events by start time
        sorted_events = sorted(events, key=lambda e: e["start"].get("dateTime", e["start"].get("date", "")))
        
        for event in sorted_events:
            message.append(format_event_markdown(event))
    
    return "\n".join(message)
