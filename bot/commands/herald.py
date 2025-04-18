# ╔════════════════════════════════════════════════════════════════════════════╗
# ║                  CALENDAR BOT HERALD COMMAND HANDLER                     ║
# ║    Handles posting of daily and weekly event summaries for users          ║
# ╚════════════════════════════════════════════════════════════════════════════╝

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
from utils.message_formatter import format_daily_message, format_weekly_message

# ╔════════════════════════════════════════════════════════════════════════════╗
# ║ LONG MESSAGE SENDING UTILITY                                              ║
# ╚════════════════════════════════════════════════════════════════════════════╝
async def send_long_message(interaction, message, ephemeral=True):
    max_length = 2000
    if len(message) <= max_length:
        await interaction.followup.send(message, ephemeral=ephemeral)
        return
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

# ╔════════════════════════════════════════════════════════════════════════════╗
# ║ POST TAGGED EVENTS                                                        ║
# ╚════════════════════════════════════════════════════════════════════════════╝
async def post_tagged_events(interaction: Interaction, day: date):
    try:
        user_id = str(interaction.user.id)
        calendars = GROUPED_CALENDARS.get(user_id)
        if not calendars:
            await interaction.followup.send("No calendars configured", ephemeral=True)
            return False
        events_by_source = defaultdict(list)
        for meta in calendars:
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

# ╔════════════════════════════════════════════════════════════════════════════╗
# ║ POST TAGGED WEEK                                                          ║
# ╚════════════════════════════════════════════════════════════════════════════╝
async def post_tagged_week(interaction: Interaction, monday: date):
    try:
        user_id = str(interaction.user.id)
        events_by_day = defaultdict(list)
        for meta in GROUPED_CALENDARS.get(user_id, []):
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

# ╔════════════════════════════════════════════════════════════════════════════╗
# ║ HERALD COMMAND HANDLER                                                    ║
# ╚════════════════════════════════════════════════════════════════════════════╝
async def handle_herald_command(interaction: Interaction):
    await interaction.response.defer(ephemeral=True)
    try:
        today = get_today()
        monday = get_monday_of_week(today)
        user_id = str(interaction.user.id)
        if user_id not in GROUPED_CALENDARS:
            await interaction.followup.send("⚠️ No calendars are configured for you. Please contact an admin to set up your calendars.", ephemeral=True)
            return
        daily_events = defaultdict(list)
        for meta in GROUPED_CALENDARS[user_id]:
            calendar_events = await asyncio.to_thread(get_events, meta, today, today)
            for event in calendar_events or []:
                event['calendar_id'] = meta.get('id', 'unknown')
                event['calendar_name'] = meta.get('name', 'Calendar')
                daily_events[meta['name']].extend([event])
        daily_message = format_daily_message(user_id, daily_events, today)
        await send_long_message(interaction, daily_message, ephemeral=True)
        weekly_events = defaultdict(list)
        for meta in GROUPED_CALENDARS[user_id]:
            calendar_events = await asyncio.to_thread(get_events, meta, monday, monday + timedelta(days=6))
            for event in calendar_events or []:
                event['calendar_id'] = meta.get('id', 'unknown')
                event['calendar_name'] = meta.get('name', 'Calendar')
                start_date = datetime.fromisoformat(event['start'].get('dateTime', event['start'].get('date'))).date()
                weekly_events[start_date].append(event)
        if today in weekly_events:
            weekly_events.pop(today)
        weekly_message = format_weekly_message(user_id, weekly_events, monday)
        await send_long_message(interaction, weekly_message, ephemeral=True)
    except Exception as e:
        logger.exception(f"Herald command error: {e}")
        await interaction.followup.send("⚠️ Failed to retrieve your events", ephemeral=True)

# ╔════════════════════════════════════════════════════════════════════════════╗
# ║ COMMAND REGISTRATION                                                      ║
# ╚════════════════════════════════════════════════════════════════════════════╝
async def register(bot: discord.Client):
    @bot.tree.command(name="herald")
    async def herald_command(interaction: discord.Interaction):
        await handle_herald_command(interaction)
