from datetime import date, timedelta
from typing import Optional
import discord
from discord import Interaction
from collections import defaultdict

from bot.events import GROUPED_CALENDARS, TAG_NAMES, get_events
from utils import format_message_lines
from .utilities import _retry_discord_operation, check_channel_permissions
from utils.logging import logger

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
            events = await _retry_discord_operation(lambda: get_events(meta, day, day))
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
            events = await _retry_discord_operation(
                lambda: get_events(meta, monday, monday + timedelta(days=6))
            )
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
