import discord
from datetime import datetime, timedelta
from typing import List, Dict, Any
from src.core.logger import logger

# ╔════════════════════════════════════════════════════════════════════╗
# ║ 🎨 Discord Embed Creation                                          ║
# ║ Creates rich embeds for displaying calendar events                 ║
# ╚════════════════════════════════════════════════════════════════════╝

def create_events_embed(events: List[Dict[str, Any]], tag: str, days: int) -> discord.Embed:
    """Create a Discord embed for displaying events."""
    try:
        embed = discord.Embed(
            title=f"📅 Upcoming Events - {tag}",
            description=f"Events for the next {days} days",
            color=0x3498db,
            timestamp=datetime.now()
        )
        
        if not events:
            embed.add_field(
                name="No Events",
                value="No events found for the specified period.",
                inline=False
            )
            return embed
        
        # Group events by date
        events_by_date = {}
        for event in events:
            try:
                # Extract date from event
                start_time = event.get('start', {})
                if 'dateTime' in start_time:
                    event_date = datetime.fromisoformat(start_time['dateTime'].replace('Z', '+00:00')).date()
                elif 'date' in start_time:
                    event_date = datetime.fromisoformat(start_time['date']).date()
                else:
                    continue
                
                date_str = event_date.strftime("%A, %B %d")
                if date_str not in events_by_date:
                    events_by_date[date_str] = []
                events_by_date[date_str].append(event)
            except Exception as e:
                logger.warning(f"Error processing event for embed: {e}")
                continue
        
        # Add events to embed, grouped by date
        for date_str, date_events in events_by_date.items():
            event_lines = []
            for event in date_events[:5]:  # Limit to 5 events per day
                try:
                    title = event.get('summary', 'Event')
                    start_time = event.get('start', {})
                    
                    # Format time
                    if 'dateTime' in start_time:
                        dt = datetime.fromisoformat(start_time['dateTime'].replace('Z', '+00:00'))
                        time_str = dt.strftime("%I:%M %p")
                    else:
                        time_str = "All day"
                    
                    # Add location if available
                    location = event.get('location', '')
                    if location:
                        event_lines.append(f"**{time_str}** - {title}\n📍 {location}")
                    else:
                        event_lines.append(f"**{time_str}** - {title}")
                        
                except Exception as e:
                    logger.warning(f"Error formatting event: {e}")
                    continue
            
            if len(date_events) > 5:
                event_lines.append(f"... and {len(date_events) - 5} more events")
            
            embed.add_field(
                name=date_str,
                value="\n".join(event_lines) if event_lines else "No events",
                inline=False
            )
        
        # Add footer with total count
        total_events = len(events)
        embed.set_footer(text=f"Total: {total_events} event{'s' if total_events != 1 else ''}")
        
        return embed
        
    except Exception as e:
        logger.exception(f"Error creating events embed: {e}")
        # Return error embed
        error_embed = discord.Embed(
            title="❌ Error",
            description="Failed to create events display",
            color=0xe74c3c
        )
        return error_embed

def create_announcement_embed(greeting: str, events: List[Dict[str, Any]], persona: str) -> discord.Embed:
    """Create an announcement embed with greeting and events."""
    try:
        embed = discord.Embed(
            title="🏰 Daily Calendar Announcement",
            description=greeting,
            color=0x9b59b6,
            timestamp=datetime.now()
        )
        
        # Add events summary if any
        if events:
            today_events = []
            upcoming_events = []
            today = datetime.now().date()
            
            for event in events:
                try:
                    start_time = event.get('start', {})
                    if 'dateTime' in start_time:
                        event_date = datetime.fromisoformat(start_time['dateTime'].replace('Z', '+00:00')).date()
                    elif 'date' in start_time:
                        event_date = datetime.fromisoformat(start_time['date']).date()
                    else:
                        continue
                    
                    title = event.get('summary', 'Event')
                    if event_date == today:
                        today_events.append(title)
                    else:
                        upcoming_events.append(f"{title} ({event_date.strftime('%m/%d')})")
                        
                except Exception as e:
                    logger.warning(f"Error processing event for announcement: {e}")
                    continue
            
            if today_events:
                embed.add_field(
                    name="📅 Today's Events",
                    value="\n".join(f"• {event}" for event in today_events[:5]),
                    inline=False
                )
            
            if upcoming_events:
                embed.add_field(
                    name="🔮 Upcoming Events",
                    value="\n".join(f"• {event}" for event in upcoming_events[:5]),
                    inline=False
                )
        
        embed.set_footer(text=f"Generated by {persona}")
        
        return embed
        
    except Exception as e:
        logger.exception(f"Error creating announcement embed: {e}")
        # Return simple embed with just the greeting
        simple_embed = discord.Embed(
            title="🏰 Daily Announcement",
            description=greeting,
            color=0x9b59b6,
            timestamp=datetime.now()
        )
        simple_embed.set_footer(text=f"Generated by {persona}")
        return simple_embed