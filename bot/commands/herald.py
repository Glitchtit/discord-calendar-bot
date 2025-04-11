from datetime import date, timedelta, datetime
from typing import Optional
import discord
from discord import Interaction
from collections import defaultdict

from bot.events import GROUPED_CALENDARS, TAG_NAMES, get_events
from utils import format_message_lines, get_today, get_monday_of_week
from .utilities import _retry_discord_operation, check_channel_permissions, send_embed
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

async def handle_herald_command(interaction: Interaction):
    """Main handler for the herald command that shows all events for the day and week"""
    await interaction.response.defer()
    try:
        today = get_today()
        monday = get_monday_of_week(today)
        
        # Post today's events
        embed_today = discord.Embed(
            title=f"📅 Today's Events ({today.strftime('%A, %B %d')})",
            color=0x3498db
        )
        
        # Post week's events
        embed_week = discord.Embed(
            title=f"📆 This Week's Schedule (Week of {monday.strftime('%B %d')})",
            color=0x9b59b6
        )
        
        # Check if user has any calendars
        user_id = str(interaction.user.id)
        if user_id not in GROUPED_CALENDARS:
            await interaction.followup.send("⚠️ No calendars are configured for you. Please contact an admin to set up your calendars.", ephemeral=True)
            return
        
        # Get daily events
        daily_events = defaultdict(list)
        for meta in GROUPED_CALENDARS[user_id]:
            events = await _retry_discord_operation(lambda: get_events(meta, today, today))
            for event in events or []:
                daily_events[meta['name']].extend([event])
        
        # Get weekly events
        weekly_events = defaultdict(list)
        for meta in GROUPED_CALENDARS[user_id]:
            events = await _retry_discord_operation(lambda: get_events(meta, monday, monday + timedelta(days=6)))
            for event in events or []:
                start_date = datetime.fromisoformat(event['start'].get('dateTime', event['start'].get('date'))).date()
                weekly_events[start_date].append(event)
        
        # Format and send the messages
        if not daily_events:
            await interaction.followup.send("📅 No events scheduled for today!", ephemeral=True)
        else:
            daily_message = format_message_lines(user_id, daily_events, today)
            await interaction.followup.send(daily_message, ephemeral=True)
        
        if not weekly_events:
            await interaction.followup.send("📆 No events scheduled for this week!", ephemeral=True)
        else:
            weekly_message = format_message_lines(user_id, weekly_events, monday)
            await interaction.followup.send(weekly_message, ephemeral=True)
            
    except Exception as e:
        logger.exception(f"Herald command error: {e}")
        await interaction.followup.send("⚠️ Failed to retrieve your events", ephemeral=True)

async def register(bot: discord.Client):
    @bot.tree.command(name="herald")
    async def herald_command(interaction: discord.Interaction):
        """Post today's and weekly events from your calendars"""
        await handle_herald_command(interaction)
