from datetime import date, timedelta, datetime
from typing import Optional
import discord
from discord import Interaction
from collections import defaultdict
import asyncio

from bot.events import GROUPED_CALENDARS, TAG_NAMES, get_events
from utils import format_message_lines, get_today, get_monday_of_week, format_event
from .utilities import _retry_discord_operation, check_channel_permissions, send_embed
from utils.logging import logger
from utils.markdown_formatter import format_daily_message, format_weekly_message

# Helper function to send long messages in chunks
async def send_long_message(interaction, message, ephemeral=True):
    """Send a message in chunks if it exceeds Discord's 2000 character limit."""
    max_length = 2000
    if len(message) <= max_length:
        await interaction.followup.send(message, ephemeral=ephemeral)
        return
    # Split by lines, try to keep formatting
    lines = message.split('\n')
    chunk = ''
    for line in lines:
        if len(chunk) + len(line) + 1 > max_length:
            await interaction.followup.send(chunk, ephemeral=ephemeral)
            chunk = ''
        if chunk:
            chunk += '\n'
        chunk += line
    if chunk:
        await interaction.followup.send(chunk, ephemeral=ephemeral)

# Herald command implementations
async def post_tagged_events(interaction: Interaction, day: date):
    try:
        user_id = str(interaction.user.id)
        calendars = GROUPED_CALENDARS.get(user_id)
        
        if not calendars:
            await interaction.followup.send("No calendars configured", ephemeral=True)
            return False

        events_by_source = defaultdict(list)
        for meta in calendars:
            # Convert synchronous get_events into an awaitable using to_thread
            events = await asyncio.to_thread(get_events, meta, day, day)
            events_by_source[meta['name']].extend(events or [])

        if not events_by_source:
            await interaction.followup.send(f"No events for {day.strftime('%Y-%m-%d')}", ephemeral=True)
            return False

        message = format_message_lines(user_id, events_by_source, day)
        await interaction.followup.send(message, ephemeral=True)
        return True
    except Exception as e:
        logger.error(f"Herald error: {e}")
        await interaction.followup.send("Failed to retrieve events", ephemeral=True)
        return False

async def post_tagged_week(interaction: Interaction, monday: date):
    try:
        user_id = str(interaction.user.id)
        events_by_day = defaultdict(list)
        
        for meta in GROUPED_CALENDARS.get(user_id, []):
            # Convert synchronous get_events into an awaitable using to_thread
            events = await asyncio.to_thread(get_events, meta, monday, monday + timedelta(days=6))
            for e in events or []:
                start_date = datetime.fromisoformat(e['start'].get('dateTime', e['start'].get('date'))).date()
                events_by_day[start_date].append(e)

        if not events_by_day:
            await interaction.followup.send("No weekly events found", ephemeral=True)
            return

        message = format_message_lines(user_id, events_by_day, monday)
        await interaction.followup.send(message, ephemeral=True)
    except Exception as e:
        logger.error(f"Weekly herald error: {e}")
        await interaction.followup.send("Failed to retrieve weekly schedule", ephemeral=True)

async def handle_herald_command(interaction: Interaction):
    """Main handler for the herald command that shows all events for the day and week"""
    await interaction.response.defer(ephemeral=True)  # Make sure defer is also ephemeral
    try:
        today = get_today()
        monday = get_monday_of_week(today)
        
        # Check if user has any calendars
        user_id = str(interaction.user.id)
        if user_id not in GROUPED_CALENDARS:
            await interaction.followup.send("⚠️ No calendars are configured for you. Please contact an admin to set up your calendars.", ephemeral=True)
            return
        
        # Get daily events
        daily_events = defaultdict(list)
        for meta in GROUPED_CALENDARS[user_id]:
            # Convert synchronous get_events into an awaitable using to_thread
            calendar_events = await asyncio.to_thread(get_events, meta, today, today)
            # Add calendar metadata to each event for color coding
            for event in calendar_events or []:
                event['calendar_id'] = meta.get('id', 'unknown')
                event['calendar_name'] = meta.get('name', 'Calendar')
                daily_events[meta['name']].extend([event])
        
        # Format and send the daily events message
        daily_message = format_daily_message(user_id, daily_events, today)
        await send_long_message(interaction, daily_message, ephemeral=True)
        
        # Get weekly events
        weekly_events = defaultdict(list)
        for meta in GROUPED_CALENDARS[user_id]:
            # Convert synchronous get_events into an awaitable using to_thread
            calendar_events = await asyncio.to_thread(get_events, meta, monday, monday + timedelta(days=6))
            # Add calendar metadata to each event for color coding
            for event in calendar_events or []:
                event['calendar_id'] = meta.get('id', 'unknown')
                event['calendar_name'] = meta.get('name', 'Calendar')
                start_date = datetime.fromisoformat(event['start'].get('dateTime', event['start'].get('date'))).date()
                weekly_events[start_date].append(event)
        
        # Filter out today's events from the weekly view to avoid duplication
        if today in weekly_events:
            weekly_events.pop(today)
        
        # Format and send the weekly events message
        weekly_message = format_weekly_message(user_id, weekly_events, monday)
        await send_long_message(interaction, weekly_message, ephemeral=True)
            
    except Exception as e:
        logger.exception(f"Herald command error: {e}")
        await interaction.followup.send("⚠️ Failed to retrieve your events", ephemeral=True)

async def register(bot: discord.Client):
    @bot.tree.command(name="herald")
    async def herald_command(interaction: discord.Interaction):
        """Post today's and weekly events from your calendars"""
        await handle_herald_command(interaction)
