# ╔════════════════════════════════════════════════════════════════════════════╗
# ║                  CALENDAR BOT AGENDA COMMAND HANDLER                     ║
# ║    Handles agenda queries for specific dates and user calendars           ║
# ╚════════════════════════════════════════════════════════════════════════════╝

"""
Handles the `/agenda` slash command.

Allows users to query their configured Google Calendars for events on a specific date.
Uses `dateparser` to interpret natural language date inputs.
Fetches events using `bot.events.get_events` and formats the output.
"""

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
from utils.message_formatter import format_agenda_message

# ╔════════════════════════════════════════════════════════════════════════════╗
# ║ AGENDA COMMAND HANDLER                                                    ║
# ╚════════════════════════════════════════════════════════════════════════════╝

# --- handle_agenda_command ---
# The core logic for the /agenda slash command.
# 1. Defers the interaction response (ephemeral) while processing.
# 2. Ensures calendar data is loaded.
# 3. Determines server timezone and preferred date formats (DMY/MDY) for `dateparser`.
# 4. Parses the user-provided `date_str` using `dateparser` with appropriate settings.
# 5. Handles invalid date input.
# 6. Retrieves the user's associated calendar sources from `GROUPED_CALENDARS`.
# 7. Handles cases where the user has no configured calendars.
# 8. Fetches events for the target date from each source using `get_events` (with retries).
# 9. Groups fetched events by day.
# 10. Handles cases where no events are found for the target date.
# 11. Formats the agenda using `format_agenda_message`.
# 12. Sends the formatted agenda as an ephemeral follow-up message.
# 13. Includes error handling for the entire process.
# Args:
#     interaction: The discord.Interaction object from the command invocation.
#     date_str: The date string provided by the user (e.g., "today", "next friday", "12/25").
async def handle_agenda_command(interaction: Interaction, date_str: str):
    await interaction.response.defer(ephemeral=True)
    try:
        ensure_calendars_loaded()
        server_id = str(interaction.guild_id) if interaction.guild else None
        server_tz = None
        date_formats = None
        if server_id:
            server_config = get_server_config(server_id)
            if server_config:
                server_tz = get_server_timezone(server_id)
                if server_tz:
                    if any(tz_part in server_tz.lower() for tz_part in ['europe', 'berlin', 'paris', 'rome', 'madrid', 'amsterdam', 'stockholm']):
                        date_formats = ['%d.%m.%Y', '%d.%m', '%d/%m/%Y', '%d/%m']
                    elif any(tz_part in server_tz.lower() for tz_part in ['america', 'us', 'new_york', 'chicago', 'denver', 'los_angeles']):
                        date_formats = ['%m.%d.%Y', '%m.%d', '%m/%d/%Y', '%m/%d']
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
        user_id = str(interaction.user.id)
        sources = GROUPED_CALENDARS.get(user_id, [])
        if not sources:
            logger.warning(f"No calendars found for user {user_id}. GROUPED_CALENDARS has keys: {list(GROUPED_CALENDARS.keys())}")
            await interaction.followup.send("⚠️ No calendars are configured for you. Please contact an admin for help.", ephemeral=True)
            return
        logger.info(f"Found {len(sources)} calendar sources for user {user_id}")
        events_by_day = defaultdict(list)
        total_events = 0
        source_name = None
        for meta in sources:
            source_name = meta.get('display_name', meta.get('name', 'Calendar'))
            try:
                calendar_events = await _retry_discord_operation(lambda: get_events(meta, target_date, target_date))
                for event in calendar_events or []:
                    event['calendar_id'] = meta.get('id', 'unknown')
                    event['calendar_name'] = meta.get('name', 'Calendar')
                    start_dt = event["start"].get("dateTime", event["start"].get("date", ""))
                    if start_dt:
                        if "T" in start_dt:
                            event_date = datetime.fromisoformat(start_dt.replace('Z', '+00:00')).date()
                        else:
                            event_date = datetime.fromisoformat(start_dt).date()
                        events_by_day[event_date].append(event)
                        total_events += 1
            except Exception as e:
                logger.error(f"Error fetching events for {meta['name']}: {e}")
        if total_events == 0:
            await interaction.followup.send(f"📅 No events found for {target_date.strftime('%A, %B %d')}", ephemeral=True)
            return
        formatted_message = format_agenda_message(user_id, events_by_day, target_date, source_name)
        await interaction.followup.send(formatted_message, ephemeral=True)
    except Exception as e:
        logger.exception(f"Error in agenda command: {e}")
        await interaction.followup.send("⚠️ An error occurred while fetching your agenda.", ephemeral=True)

# ╔════════════════════════════════════════════════════════════════════════════╗
# ║ COMMAND REGISTRATION                                                      ║
# ╚════════════════════════════════════════════════════════════════════════════╝

# --- register ---
# Registers the /agenda slash command with the bot's command tree.
# This function is typically called during bot setup.
# It defines the command name, description, and parameters.
# Args:
#     bot: The discord.Client or discord.ext.commands.Bot instance.
async def register(bot: discord.Client):
    # --- agenda_command ---
    # The actual slash command function decorated with `@bot.tree.command`.
    # This is the function directly invoked by Discord when the command is used.
    # It takes the interaction and the required 'date' string argument.
    # It simply calls `handle_agenda_command` to process the request.
    # Args:
    #     interaction: The discord.Interaction object.
    #     date: The date string input from the user.
    @bot.tree.command(name="agenda", description="Shows your agenda for a specific date (e.g., 'today', 'tomorrow', 'next friday').")
    async def agenda_command(interaction: discord.Interaction, date: str):
        """Shows your agenda for a specific date."""
        await handle_agenda_command(interaction, date)
    logger.info("Registered /agenda command.")