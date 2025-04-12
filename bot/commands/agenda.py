from datetime import date, datetime, timedelta
import discord
from discord import Interaction
import dateparser
from collections import defaultdict

from bot.events import GROUPED_CALENDARS, get_events, ensure_calendars_loaded
from utils.logging import logger
from utils import format_message_lines
from utils.timezone_utils import get_server_timezone
from utils.server_utils import get_server_config
from .utilities import _retry_discord_operation

# Agenda command implementation
async def handle_agenda_command(interaction: Interaction, date_str: str):
    await interaction.response.defer(ephemeral=True)
    try:
        # Make sure calendars are loaded first
        ensure_calendars_loaded()
        
        # Get the server's timezone to determine date format preference
        server_id = str(interaction.guild_id) if interaction.guild else None
        server_tz = None
        date_formats = None
        
        if server_id:
            server_config = get_server_config(server_id)
            if server_config:
                server_tz = get_server_timezone(server_id)
                
                # Determine date format preference based on timezone
                # European/most of world tends to use DD.MM format
                # US/North America tends to use MM.DD format
                if server_tz:
                    if any(tz_part in server_tz.lower() for tz_part in ['europe', 'berlin', 'paris', 'rome', 'madrid', 'amsterdam', 'stockholm']):
                        date_formats = ['%d.%m.%Y', '%d.%m', '%d/%m/%Y', '%d/%m']
                    elif any(tz_part in server_tz.lower() for tz_part in ['america', 'us', 'new_york', 'chicago', 'denver', 'los_angeles']):
                        date_formats = ['%m.%d.%Y', '%m.%d', '%m/%d/%Y', '%m/%d']
        
        # Parse the date string using dateparser with appropriate settings
        settings = {
            'PREFER_DATES_FROM': 'future',
            'RETURN_AS_TIMEZONE_AWARE': True
        }
        
        if date_formats:
            settings['DATE_ORDER'] = 'DMY' if date_formats[0].startswith('%d') else 'MDY'
            
        if server_tz:
            settings['TIMEZONE'] = server_tz
            
        parsed_date = dateparser.parse(date_str, settings=settings)
        if not parsed_date:
            await interaction.followup.send("⚠️ Could not parse the date. Try formats like 'today', 'tomorrow', 'next friday', etc.", ephemeral=True)
            return
            
        target_date = parsed_date.date()
        
        # Use the user's own ID to find their calendars
        user_id = str(interaction.user.id)
        sources = GROUPED_CALENDARS.get(user_id, [])
        
        if not sources:
            logger.warning(f"No calendars found for user {user_id}. GROUPED_CALENDARS has keys: {list(GROUPED_CALENDARS.keys())}")
            await interaction.followup.send("⚠️ No calendars are configured for you. Please contact an admin for help.", ephemeral=True)
            return
        
        # Log for debugging
        logger.info(f"Found {len(sources)} calendar sources for user {user_id}")
            
        events_by_day = defaultdict(list)
        total_events = 0
        
        # Fetch events from all sources
        for meta in sources:
            try:
                # Fix: _retry_discord_operation is async, so we need to await it
                events = await _retry_discord_operation(lambda: get_events(meta, target_date, target_date))
                
                # Group events by day
                for event in events or []:
                    start_dt = event["start"].get("dateTime", event["start"].get("date", ""))
                    if start_dt:
                        # Convert to date obj if needed
                        if "T" in start_dt:  # Has time component
                            event_date = datetime.fromisoformat(start_dt.replace('Z', '+00:00')).date()
                        else:  # Date only
                            event_date = datetime.fromisoformat(start_dt).date()
                        events_by_day[event_date].append(event)
                        total_events += 1
            except Exception as e:
                logger.error(f"Error fetching events for {meta['name']}: {e}")
        
        # Create response message
        if total_events == 0:
            await interaction.followup.send(f"📅 No events found for {target_date.strftime('%A, %B %d')}", ephemeral=True)
            return
            
        # Format the message with improved formatting
        formatted_message = format_agenda_message(user_id, events_by_day, target_date, sources)
        
        # Create embed response
        embed = discord.Embed(
            title=f"📅 Agenda for {target_date.strftime('%A, %B %d')}",
            description=formatted_message,
            color=0x3498db
        )
        
        await interaction.followup.send(embed=embed, ephemeral=True)
        
    except Exception as e:
        logger.exception(f"Error in agenda command: {e}")
        await interaction.followup.send("⚠️ An error occurred while fetching your agenda.", ephemeral=True)

def format_agenda_message(user_id, events_by_day, target_date, sources):
    """
    Format events into a clean, readable message for the agenda command.
    Similar to the formatting style used by the herald command.
    """
    message_lines = []
    
    # Get the source name for better display
    source_name = None
    for meta in sources:
        if meta.get('user_id') == user_id:
            source_name = meta.get('display_name', meta.get('name', 'Calendar'))
            break
    
    if not source_name:
        source_name = "Your calendar"
    
    for day_date, day_events in events_by_day.items():
        # Format date header nicely
        date_str = day_date.strftime("%A, %B %d")
        
        # Add events under this day
        if day_events:
            message_lines.append(f"**Events for {date_str}:**")
            
            # Sort events by start time
            day_events.sort(key=lambda e: e["start"].get("dateTime", e["start"].get("date", "")))
            
            for event in day_events:
                # Get event details
                event_name = event.get("summary", "Untitled Event")
                
                # Format event time
                start_dt = event["start"].get("dateTime")
                end_dt = event["end"].get("dateTime")
                
                if start_dt and end_dt:  # Has specific times
                    start = datetime.fromisoformat(start_dt.replace('Z', '+00:00'))
                    end = datetime.fromisoformat(end_dt.replace('Z', '+00:00'))
                    time_str = f"{start.strftime('%H:%M')}–{end.strftime('%H:%M')}"
                else:  # All-day event
                    time_str = "All day"
                
                # Add formatted event line
                message_lines.append(f"• **{event_name}** {time_str}")
            
            message_lines.append("")  # Add empty line for spacing
    
    return "\n".join(message_lines)

async def register(bot: discord.Client):
    @bot.tree.command(name="agenda")
    async def agenda_command(interaction: discord.Interaction, date: str):
        """Get events for a specific date"""
        await handle_agenda_command(interaction, date)