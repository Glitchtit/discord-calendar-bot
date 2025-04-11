from datetime import date, datetime, timedelta
import discord
from discord import Interaction
import dateparser
from collections import defaultdict

from bot.events import GROUPED_CALENDARS, get_events
from utils.logging import logger
from utils import format_message_lines
from .utilities import _retry_discord_operation

# Agenda command implementation
async def handle_agenda_command(interaction: Interaction, date_str: str):
    await interaction.response.defer(ephemeral=True)
    try:
        # Parse the date string using dateparser for natural language support
        parsed_date = dateparser.parse(date_str)
        if not parsed_date:
            await interaction.followup.send("⚠️ Could not parse the date. Try formats like 'today', 'tomorrow', 'next friday', etc.", ephemeral=True)
            return
            
        target_date = parsed_date.date()
        
        # Use the user's own ID to find their calendars
        user_id = str(interaction.user.id)
        sources = GROUPED_CALENDARS.get(user_id, [])
        
        if not sources:
            await interaction.followup.send("⚠️ No calendars are configured for you. Please contact an admin for help.", ephemeral=True)
            return
            
        events_by_day = defaultdict(list)
        total_events = 0
        
        # Fetch events from all sources
        for meta in sources:
            try:
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
            
        # Format the message
        formatted_message = format_message_lines(user_id, events_by_day, target_date)
        
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

async def register(bot: discord.Client):
    @bot.tree.command(name="agenda")
    async def agenda_command(interaction: discord.Interaction, date: str):
        """Get events for a specific date"""
        await handle_agenda_command(interaction, date)
