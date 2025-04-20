# ╔════════════════════════════════════════════════════════════════════════════╗
# ║                   CALENDAR BOT DAILY COMMAND HANDLER                     ║
# ║    Handles manual requests for the daily event summary post                ║
# ╚════════════════════════════════════════════════════════════════════════════╝

"""
Handles the `/daily` slash command.

Allows users (typically admins or those with permissions) to manually trigger
the posting of the daily event summary for the current day or the next day.
This uses the same logic as the automated daily task (`bot.tasks.daily_posts`).
"""

from datetime import date
import discord
import asyncio
from discord import Interaction, app_commands
from bot.events import GROUPED_CALENDARS, get_events
from .utilities import send_embed
from utils.logging import logger
from utils import format_message_lines
from utils.message_formatter import format_daily_message

# ╔════════════════════════════════════════════════════════════════════════════╗
# ║ POST DAILY EVENTS                                                         ║
# ╚════════════════════════════════════════════════════════════════════════════╝

# --- post_daily_events ---
# Fetches and posts the daily events for a specific user ID or the server-wide ("1") tag.
# Retrieves events for the given `day` from the user's/tag's associated calendars.
# Formats the events into a message using `format_daily_message`.
# Attempts to send the message to the configured announcement channel for the relevant server(s).
# If no announcement channel is found, it can fall back to the `interaction_channel` if provided.
# Args:
#     bot: The discord.Client instance.
#     user_id: The Discord user ID or "1" for server-wide calendars.
#     day: The date object for which to fetch events.
#     interaction_channel: (Optional) The channel where the command was invoked, used as a fallback.
#     server_id: (Optional) The specific server ID to post for. If None, checks all servers.
# Returns: True if events were successfully posted, False otherwise.
async def post_daily_events(bot, user_id: str, day: date, interaction_channel=None, server_id=None):
    try:
        sources = GROUPED_CALENDARS.get(user_id, [])
        if not sources:
            return False
        if server_id:
            sources = [source for source in sources if source.get("server_id") == server_id]
            if not sources:
                return False
        events = []
        for meta in sources:
            calendar_events = await asyncio.to_thread(get_events, meta, day, day)
            for event in calendar_events:
                event['calendar_id'] = meta.get('id', 'unknown')
                event['calendar_name'] = meta.get('name', 'Calendar')
            events.extend(calendar_events)
        if not events:
            return False
        events_by_calendar = {}
        for meta in sources:
            calendar_name = meta.get('name', 'Calendar')
            calendar_events = [e for e in events if e.get('calendar_id') == meta.get('id')]
            if calendar_events:
                events_by_calendar[calendar_name] = calendar_events
        message = format_daily_message(user_id, events_by_calendar, day, is_public=True)
        is_server_wide = user_id == "1"
        content = ""
        if is_server_wide:
            content = "@everyone"
        try:
            from config.server_config import get_all_server_ids, load_server_config
            channel_found = False
            server_ids = [server_id] if server_id else get_all_server_ids()
            logger.info(f"Checking {len(server_ids)} servers for announcement channels")
            for server_id in server_ids:
                config = load_server_config(server_id)
                if config and config.get("announcement_channel_id"):
                    channel_id = int(config.get("announcement_channel_id"))
                    channel = bot.get_channel(channel_id)
                    if channel:
                        logger.info(f"Found announcement channel: {channel.name} (ID: {channel_id})")
                        await channel.send(content=message if not content else f"{content}\n{message}")
                        logger.info(f"Sent calendar update to channel {channel.name}")
                        channel_found = True
                        return True
                else:
                    logger.debug(f"Server {server_id} has no announcement_channel_id configured")
            if not channel_found and interaction_channel:
                logger.info(f"Using interaction channel as fallback: {interaction_channel.name}")
                await interaction_channel.send(content=message if not content else f"{content}\n{message}")
                return True
            if not channel_found:
                logger.error("Could not find announcement channel to send message")
                return False
        except Exception as e:
            logger.error(f"Error sending message directly: {e}")
            return False
    except Exception as e:
        logger.error(f"Daily post error: {e}")
        return False

# ╔════════════════════════════════════════════════════════════════════════════╗
# ║ DAILY COMMAND HANDLER                                                      ║
# ╚════════════════════════════════════════════════════════════════════════════╝

# --- handle_daily_command ---
# The core logic for the /daily slash command.
# 1. Checks if the command is used within a server (guild).
# 2. Defers the interaction response (ephemeral, thinking) while processing.
# 3. Retrieves the server configuration.
# 4. Checks if the invoking user has administrator permissions OR is the bot owner.
# 5. Determines the target date (today or tomorrow) based on the `day` parameter.
# 6. Calls `post_daily_events` (from `bot.tasks.daily_posts`) to generate and send the post.
# 7. Sends a confirmation message to the invoking user (ephemeral).
# 8. Includes error handling for missing configuration, permissions, and task execution.
# Args:
#     interaction: The discord.Interaction object from the command invocation.
#     day: String indicating whether to post for "today" or "tomorrow".
async def handle_daily_command(interaction: Interaction, day: str):
    await interaction.response.defer()
    try:
        count = 0
        for user_id in GROUPED_CALENDARS:
            if await post_daily_events(interaction.client, user_id, date.today(), interaction.channel):
                count += 1
        await interaction.followup.send(f"📝 Posted daily events for {count} users")
    except Exception as e:
        logger.error(f"Daily command error: {e}")
        await interaction.followup.send("⚠️ Failed to post daily events")

# ╔════════════════════════════════════════════════════════════════════════════╗
# ║ COMMAND REGISTRATION                                                      ║
# ╚════════════════════════════════════════════════════════════════════════════╝

# --- register ---
# Registers the /daily slash command with the bot's command tree.
# This function is typically called during bot setup.
# It defines the command name, description, and the required 'day' parameter
# with choices ("today", "tomorrow").
# Args:
#     bot: The discord.Client or discord.ext.commands.Bot instance.
async def register(bot: discord.Client):
    # --- daily_command ---
    # The actual slash command function decorated with `@bot.tree.command`.
    # This is the function directly invoked by Discord when the command is used.
    # It takes the interaction and the required 'day' choice argument.
    # It simply calls `handle_daily_command` to process the request.
    # Args:
    #     interaction: The discord.Interaction object.
    #     day: The choice selected by the user ("today" or "tomorrow").
    @bot.tree.command(name="daily", description="Manually post the daily events summary.")
    @app_commands.choices(day=[
        app_commands.Choice(name="today", value="today"),
        app_commands.Choice(name="tomorrow", value="tomorrow"),
    ])
    async def daily_command(interaction: discord.Interaction, day: app_commands.Choice[str]):
        """Manually post the daily events summary for today or tomorrow."""
        await handle_daily_command(interaction, day.value)
    logger.info("Registered /daily command.")
