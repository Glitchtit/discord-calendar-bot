# ╔════════════════════════════════════════════════════════════════════════════╗
# ║                  CALENDAR BOT WEEKLY COMMAND HANDLER                       ║
# ║    Handles posting of weekly event summaries for users                     ║
# ╚════════════════════════════════════════════════════════════════════════════╝

from datetime import date, timedelta, datetime
import discord
import asyncio
from discord import Interaction
from collections import defaultdict
from bot.events import GROUPED_CALENDARS, get_events
from .utilities import send_embed
from utils.logging import logger
from utils import format_message_lines, get_monday_of_week
from utils.message_formatter import format_weekly_message
from config.server_config import get_announcement_channel_id
from utils import split_message_by_lines

# ╔════════════════════════════════════════════════════════════════════════════╗
# ║ POST WEEKLY EVENTS                                                        ║
# ╚════════════════════════════════════════════════════════════════════════════╝
async def post_weekly_events(bot, user_id: str, monday: date, interaction_channel=None):
    try:
        sources = GROUPED_CALENDARS.get(user_id, [])
        if not sources:
            return False
        server_id = None
        if sources:
            server_id = sources[0].get("server_id")
        sunday = monday + timedelta(days=6)
        all_events = []
        for meta in sources:
            calendar_events = await asyncio.to_thread(get_events, meta, monday, sunday)
            for event in calendar_events:
                event['calendar_id'] = meta.get('id', 'unknown')
                event['calendar_name'] = meta.get('name', 'Calendar')
            all_events.extend(calendar_events)
        if not all_events:
            return False
        events_by_day = defaultdict(list)
        for event in all_events:
            start_container = event.get("start", {})
            start_dt_str = start_container.get("dateTime", start_container.get("date"))
            if start_dt_str:
                try:
                    if 'T' in start_dt_str:
                        event_date = datetime.fromisoformat(start_dt_str.replace('Z', '+00:00')).date()
                    else:
                        event_date = date.fromisoformat(start_dt_str)
                    events_by_day[event_date].append(event)
                except ValueError:
                    logger.warning(f"Could not parse date for event: {event.get('summary')}")
        events_by_day = {day: evs for day, evs in events_by_day.items() if monday <= day <= sunday}
        if not events_by_day:
             logger.info(f"No events found for user {user_id} for the week of {monday}")
             return False
        message = format_weekly_message(user_id, events_by_day, monday)
        is_server_wide = user_id == "1"
        content = ""
        if is_server_wide:
            content = "@everyone"
        try:
            channel_id = None
            if server_id:
                channel_id = get_announcement_channel_id(server_id)
            channel = bot.get_channel(channel_id) if channel_id else None
            channel_found = bool(channel)
            if channel:
                logger.info(f"Found announcement channel: {channel.name} (ID: {channel_id}) for server {server_id}")
                message_chunks = split_message_by_lines(message, 2000)
                full_content = message if not content else f"{content}\n{message_chunks[0]}"
                await channel.send(content=full_content)
                for chunk in message_chunks[1:]:
                    await channel.send(content=chunk)
                logger.info(f"Sent weekly calendar update to channel {channel.name}")
                return True
            else:
                logger.debug(f"No announcement channel configured or found for server {server_id}")
            if not channel_found and interaction_channel:
                logger.info(f"Using interaction channel {interaction_channel.name} as fallback for server {server_id}")
                message_chunks = split_message_by_lines(message, 2000)
                full_content = message if not content else f"{content}\n{message_chunks[0]}"
                await interaction_channel.send(content=full_content)
                for chunk in message_chunks[1:]:
                    await interaction_channel.send(content=chunk)
                return True
            if not channel_found:
                logger.error(f"Could not find announcement channel for server {server_id} and no fallback interaction channel provided.")
                return False
        except Exception as e:
            logger.error(f"Error sending weekly message for server {server_id}: {e}")
            return False
    except Exception as e:
        logger.error(f"Weekly post error for user {user_id}: {e}")
        return False

# ╔════════════════════════════════════════════════════════════════════════════╗
# ║ WEEKLY COMMAND HANDLER                                                     ║
# ╚════════════════════════════════════════════════════════════════════════════╝
async def handle_weekly_command(interaction: Interaction):
    await interaction.response.defer()
    try:
        this_monday = get_monday_of_week(date.today())
        count = 0
        for user_id in GROUPED_CALENDARS:
            if await post_weekly_events(interaction.client, user_id, this_monday, interaction.channel):
                count += 1
        await interaction.followup.send(f"📝 Posted weekly events for {count} users")
    except Exception as e:
        logger.error(f"Weekly command error: {e}")
        await interaction.followup.send("⚠️ Failed to post weekly events")

# ╔════════════════════════════════════════════════════════════════════════════╗
# ║ COMMAND REGISTRATION                                                      ║
# ╚════════════════════════════════════════════════════════════════════════════╝
async def register(bot: discord.Client):
    @bot.tree.command(name="weekly")
    @discord.app_commands.checks.has_permissions(manage_messages=True)
    async def weekly_command(interaction: discord.Interaction):
        await handle_weekly_command(interaction)
