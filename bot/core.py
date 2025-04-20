# ╔════════════════════════════════════════════════════════════════════════════╗
# ║                        DISCORD CALENDAR BOT CORE MODULE                  ║
# ║    Handles bot setup, command registration, and event lifecycle logic    ║
# ╚════════════════════════════════════════════════════════════════════════════╝

import asyncio
from typing import List
import discord
from discord.ext import commands
from discord import app_commands
from datetime import datetime, timedelta
from discord.ui import View, Button, Select
from utils.logging import logger
from bot.events import (
    GROUPED_CALENDARS,
    TAG_NAMES,
    TAG_COLORS,
    get_events,
    get_service_account_email,
    load_calendars_from_server_configs,
    reinitialize_events
)
from ai import generate_greeting, generate_image
from bot.commands import (
    post_tagged_events,
    post_tagged_week,
    send_embed,
    handle_herald_command,
    handle_agenda_command,
    handle_greet_command,
    handle_reload_command,
    handle_who_command,
    handle_daily_command,
    handle_setup_command,
    handle_status_command,
    handle_weekly_command,
    handle_clear_command
)
from bot.tasks import start_all_tasks
from config.server_config import load_all_server_configs, get_announcement_channel_id
from utils.validators import detect_calendar_type
from config.server_config import (
    add_calendar, 
    remove_calendar, 
    load_server_config, 
    save_server_config,
    SERVER_CONFIG_DIR
)
from collections import defaultdict
from utils import get_today
import os
from utils.server_utils import get_all_server_ids

# ╔════════════════════════════════════════════════════════════════════════════╗
# ║ BOT INTENTS & INITIALIZATION                                              ║
# ╚════════════════════════════════════════════════════════════════════════════╝
# --- Bot Setup ---
# Defines the necessary Discord intents (permissions) for the bot.
# Initializes the discord.ext.commands.Bot instance.
intents = discord.Intents.default()
intents.members = True
bot = commands.Bot(command_prefix="/", intents=intents)
bot.is_initialized = False

# ╔════════════════════════════════════════════════════════════════════════════╗
# ║ BOT READY EVENT                                                           ║
# ╚════════════════════════════════════════════════════════════════════════════╝

# --- on_ready ---
# Event handler triggered when the bot successfully connects to Discord.
# Performs initial setup: ensures config directory exists, loads calendars,
# registers admins, syncs slash commands, initializes snapshots and subscriptions,
# starts background tasks, and sets the `is_initialized` flag.
@bot.event
async def on_ready():
    os.makedirs(SERVER_CONFIG_DIR, exist_ok=True)
    logger.info(f"Ensured server configuration directory exists: {SERVER_CONFIG_DIR}")
    logger.info(f"Logged in as {bot.user}")
    if bot.is_initialized:
        logger.info("Bot reconnected, skipping initialization")
        return
    try:
        from utils.notifications import register_discord_client
        register_discord_client(bot)
        logger.info("Loading calendar configurations...")
        load_calendars_from_server_configs()
        logger.info(f"Loaded {len(GROUPED_CALENDARS)} user/tag groups initially.")
        from config.server_config import add_admin_user
        for server_id in get_all_server_ids():
            config = load_server_config(server_id)
            owner_id = config.get("owner_id")
            if owner_id:
                logger.debug(f"Ensuring owner {owner_id} is registered as admin for server {server_id}")
                success, message = add_admin_user(server_id, str(owner_id))
                if success:
                    logger.info(f"Owner {owner_id} confirmed/added as admin for server {server_id}.")
                elif "already an admin" not in message:
                    logger.error(f"Failed to ensure owner {owner_id} as admin for server {server_id}: {message}")
            else:
                logger.warning(f"Server {server_id} does not have an owner_id defined in its config.")
        from config.server_config import get_admin_user_ids
        from utils.notifications import register_admins
        for server_id in get_all_server_ids():
            admin_ids = get_admin_user_ids(server_id)
            if admin_ids:
                register_admins(admin_ids)
                logger.info(f"Registered {len(admin_ids)} admins for server {server_id} error notifications")
            else:
                logger.warning(f"No admin users configured for server {server_id} notifications")
        synced = await bot.tree.sync()
        logger.info(f"Synced {len(synced)} commands.")
        await resolve_tag_mappings()
        from bot.tasks import initialize_event_snapshots
        await initialize_event_snapshots()
        from utils.calendar_sync import initialize_subscriptions
        await initialize_subscriptions()
        from bot.tasks import start_all_tasks
        start_all_tasks(bot)
        bot.is_initialized = True
        logger.info("Bot initialization completed successfully")
    except Exception as e:
        logger.exception(f"Error during initialization: {e}")
        try:
            from utils.notifications import notify_critical_error
            await notify_critical_error("Bot Initialization", e)
        except Exception as notify_error:
            logger.error(f"Failed to send error notification: {notify_error}")

# ╔════════════════════════════════════════════════════════════════════════════╗
# ║ BOT DISCONNECT & RESUME EVENTS                                            ║
# ╚════════════════════════════════════════════════════════════════════════════╝

# --- on_disconnect ---
# Event handler triggered when the bot loses connection to Discord.
# Logs a warning message.
@bot.event
async def on_disconnect():
    logger.warning("Bot disconnected from Discord. Waiting for reconnection...")

# --- on_resumed ---
# Event handler triggered when the bot successfully reconnects after a disconnect.
# Checks if background tasks are running, resolves tag mappings again,
# and checks for any events missed during the downtime.
@bot.event
async def on_resumed():
    logger.info("Bot connection resumed")
    try:
        from bot.tasks import check_tasks_running, start_all_tasks
        tasks_status = await check_tasks_running()
        if not tasks_status:
            logger.warning("Some scheduled tasks were not running. Restarting tasks...")
            start_all_tasks(bot)
        await resolve_tag_mappings()
        logger.info("Checking for any missed events during disconnection...")
        from bot.tasks import check_for_missed_events
        await check_for_missed_events()
        logger.info("Connection recovery completed successfully")
    except Exception as e:
        logger.exception(f"Error during connection recovery: {e}")

# ╔════════════════════════════════════════════════════════════════════════════╗
# ║ SLASH COMMAND REGISTRATION                                                ║
# ╚════════════════════════════════════════════════════════════════════════════╝

# --- herald_command ---
# Registers the /herald slash command.
# Calls the handler function from the command router.
@bot.tree.command(name="herald", description="Get a summary of all users' weekly and daily events")
async def herald_command(interaction: discord.Interaction):
    await handle_herald_command(interaction)

# --- agenda_command ---
# Registers the /agenda slash command with a required 'date' argument.
# Calls the handler function from the command router.
@bot.tree.command(name="agenda", description="See events for a specific date (natural language supported)")
async def agenda_command(interaction: discord.Interaction, date: str):
    await handle_agenda_command(interaction, date)

# --- greet_command ---
# Registers the /greet slash command.
# Calls the handler function from the command router.
@bot.tree.command(name="greet", description="Post the themed morning greeting with image")
async def greet_command(interaction: discord.Interaction):
    await handle_greet_command(interaction)

# --- reload_command ---
# Registers the /reload slash command.
# Calls the handler function from the command router.
@bot.tree.command(name="reload", description="Reload calendar sources and user mappings")
async def reload_command(interaction: discord.Interaction):
    await handle_reload_command(interaction)

# --- who_command ---
# Registers the /who slash command.
# Calls the handler function from the command router.
@bot.tree.command(name="who", description="List all calendars and their assigned users")
async def who_command(interaction: discord.Interaction):
    await handle_who_command(interaction)

# --- daily_command ---
# Registers the /daily slash command.
# Calls the handler function from the command router.
@bot.tree.command(name="daily", description="Post today's events for all users to the announcement channel")
async def daily_command(interaction: discord.Interaction):
    await handle_daily_command(interaction)

# --- setup_command ---
# Registers the /setup slash command.
# Calls the handler function from the command router.
@bot.tree.command(name="setup", description="Configure server-specific calendar settings")
async def setup_command(interaction: discord.Interaction):
    await handle_setup_command(interaction)

# --- weekly_command ---
# Registers the /weekly slash command.
# Calls the handler function from the command router.
@bot.tree.command(name="weekly", description="Post this week's events for all users to the announcement channel")
async def weekly_command(interaction: discord.Interaction):
    await handle_weekly_command(interaction)

# --- clear_command ---
# Registers the /clear slash command (Admin only).
# Requires administrator permissions.
# Calls the handler function from the command router.
@bot.tree.command(name="clear", description="[Admin] Clears all messages in the announcement channel.")
@app_commands.checks.has_permissions(administrator=True)
async def clear_command(interaction: discord.Interaction):
    await handle_clear_command(interaction)

# --- status_command ---
# Registers the /status slash command.
# Calls the handler function from the command router.
@bot.tree.command(name="status", description="View calendar health status and system metrics")
async def status_command(interaction: discord.Interaction):
    await handle_status_command(interaction)

# ╔════════════════════════════════════════════════════════════════════════════╗
# ║ AUTOCOMPLETE FUNCTIONS                                                    ║
# ╚════════════════════════════════════════════════════════════════════════════╝

# --- autocomplete_agenda_input ---
# Provides autocomplete suggestions for the 'date' argument of the /agenda command.
# Suggests relative dates like "today", "tomorrow", "week", and upcoming weekdays.
# Args:
#     interaction: The discord.Interaction object.
#     current: The currently typed input by the user.
# Returns: A list of app_commands.Choice objects for autocomplete.
async def autocomplete_agenda_input(interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
    suggestions = [
        "today", "tomorrow", "week", 
        "next monday", "next tuesday", "next wednesday", 
        "next thursday", "next friday", "next saturday", "next sunday"
    ]
    today = get_today()
    for i in range(1, 7):
        day = (today + timedelta(days=i)).strftime("%A").lower()
        if day not in suggestions:
            suggestions.append(day)
    if current:
        return [
            app_commands.Choice(name=suggestion, value=suggestion)
            for suggestion in suggestions if current.lower() in suggestion.lower()
        ][:25]
    return [app_commands.Choice(name=s, value=s) for s in suggestions[:25]]

# --- autocomplete_agenda_target ---
# Provides autocomplete suggestions for a potential (currently unused) 'target' argument.
# Suggests user/tag names based on loaded calendars.
# Args:
#     interaction: The discord.Interaction object.
#     current: The currently typed input by the user.
# Returns: A list of app_commands.Choice objects for autocomplete.
async def autocomplete_agenda_target(interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
    suggestions = []
    for tag in GROUPED_CALENDARS:
        display_name = TAG_NAMES.get(tag, tag)
        suggestions.append((display_name, display_name))
        if tag != display_name:
            suggestions.append((tag, tag))
    if current:
        filtered = [
            app_commands.Choice(name=name, value=value)
            for name, value in suggestions 
            if current.lower() in name.lower()
        ]
        return filtered[:25]
    return [app_commands.Choice(name=name, value=value) for name, value in suggestions[:25]]

# ╔════════════════════════════════════════════════════════════════════════════╗
# ║ TAG MAPPING RESOLUTION                                                    ║
# ╚════════════════════════════════════════════════════════════════════════════╝

# --- resolve_tag_mappings ---
# Iterates through all guilds (servers) the bot is in and their members.
# If a member's ID matches a key in `GROUPED_CALENDARS`, it updates the
# `TAG_NAMES` dictionary with the member's current display name.
# This keeps the display names used in commands and messages up-to-date.
async def resolve_tag_mappings():
    from bot.events import GROUPED_CALENDARS
    TAG_NAMES.clear()
    TAG_COLORS.clear()
    resolved_count = 0
    for guild in bot.guilds:
        try:
            for member in guild.members:
                if member.id in GROUPED_CALENDARS:
                    TAG_NAMES[member.id] = member.display_name
                    resolved_count += 1
        except Exception as e:
            logger.warning(f"Error resolving members for guild {guild.name}: {e}")
    logger.info(f"Resolved {resolved_count} user mappings to display names.")
