from datetime import date
import discord
import asyncio  # Add this import
from discord import Interaction
from bot.events import GROUPED_CALENDARS, get_events
from .utilities import send_embed
from utils.logging import logger
from utils import format_message_lines

async def post_daily_events(bot, user_id: str, day: date):
    try:
        sources = GROUPED_CALENDARS.get(user_id, [])
        if not sources:
            return False
        
        events = []
        for meta in sources:
            # Fix: Run get_events in a separate thread since it's synchronous
            events.extend(await asyncio.to_thread(get_events, meta, day, day))
        
        if not events:
            return False
            
        # Fix: Create a dictionary with day as the key and events as the value
        events_by_day = {day: events}
            
        message = format_message_lines(user_id, events_by_day, day)
        
        # Add a check to make sure we're not sending an empty message
        if not message or message.isspace():
            message = f"No events to display for <@{user_id}> on {day.strftime('%A, %B %d')}."
            
        await send_embed(bot, description=message)
        return True
    except Exception as e:
        logger.error(f"Daily post error: {e}")
        return False

async def handle_daily_command(interaction: Interaction):
    await interaction.response.defer()
    try:
        count = 0
        for user_id in GROUPED_CALENDARS:
            if await post_daily_events(interaction.client, user_id, date.today()):
                count += 1
        await interaction.followup.send(f"Posted daily events for {count} users")
    except Exception as e:
        logger.error(f"Daily command error: {e}")
        await interaction.followup.send("⚠️ Failed to post daily events")

async def register(bot: discord.Client):
    @bot.tree.command(name="daily")
    @discord.app_commands.checks.has_permissions(manage_messages=True)
    async def daily_command(interaction: discord.Interaction):
        """Post daily summaries to announcement channel"""
        await handle_daily_command(interaction)
