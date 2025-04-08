"""
bot.py: Discord bot setup and initialization, including command sync and error handling.

This module implements the Discord bot interface including:
- Slash commands for calendar interaction
- Setup wizard for server-specific calendar configuration
- Event monitoring and notification systems

Note: Now uses server-specific configuration via /setup command instead of
the previous environment variable approach.
"""

import sys
import asyncio
from typing import Any, List

import discord
from discord.ext import commands
from discord import app_commands
from datetime import datetime
import dateparser
import asyncio
import random
import os
from discord.ui import View, Button, Select, Modal, TextInput

from log import logger
from events import (
    GROUPED_CALENDARS,
    USER_TAG_MAP,
    TAG_NAMES,
    TAG_COLORS,
    get_events,
    get_service_account_email,
    load_calendars_from_server_configs,
    reinitialize_events
)
from ai import generate_greeting, generate_image
from commands import (
    post_tagged_events,
    post_tagged_week,
    send_embed,
)
from tasks import initialize_event_snapshots, start_all_tasks, post_todays_happenings
from utils import get_today, get_monday_of_week, resolve_input_to_tags
from server_config import (
    add_calendar, 
    remove_calendar, 
    load_server_config, 
    save_server_config,
    SERVER_CONFIG_DIR,
    get_all_server_ids,
    detect_calendar_type
)
from collections import defaultdict
from datetime import timedelta
from views import (
    CalendarSetupView,
    AddCalendarModal,
    CalendarRemoveView,
    ConfirmRemovalView
)

# ╔════════════════════════════════════════════════════════════════════╗
# 🤖 Intents & Bot Setup
# ╚════════════════════════════════════════════════════════════════════╝
intents = discord.Intents.default()
intents.members = True
bot = commands.Bot(command_prefix="/", intents=intents)

# Track initialization state to avoid duplicate startups
bot.is_initialized = False


# ╔════════════════════════════════════════════════════════════════════╗
# ⚙️ on_ready: Sync Commands & Log Bot Info
# ╚════════════════════════════════════════════════════════════════════╝
@bot.event
async def on_ready():
    logger.info(f"Logged in as {bot.user}")
    
    # Prevent multiple initializations if Discord reconnects
    if bot.is_initialized:
        logger.info("Bot reconnected, skipping initialization")
        return
    
    # Perform initialization with progressive backoff for retries
    max_retries = 3
    for attempt in range(1, max_retries + 1):
        try:
            # Step 1: Load calendars from server configurations
            load_calendars_from_server_configs()
            
            # Step 2: Resolve tag mappings
            await resolve_tag_mappings()
            
            # Step 3: Add slight delay to avoid rate limiting
            await asyncio.sleep(1)
            
            # Step 4: Sync slash commands (only once)
            synced = await bot.tree.sync()
            logger.info(f"Synced {len(synced)} commands.")
            
            # Step 5: Initialize event snapshots
            await initialize_event_snapshots()
            
            # Step 6: Start recurring tasks
            start_all_tasks(bot)
            
            # Mark successful initialization only after all steps succeed
            bot.is_initialized = True
            logger.info("Bot initialization completed successfully")
            break
            
        except discord.errors.HTTPException as e:
            # Handle Discord API issues with exponential backoff
            retry_delay = 2 ** attempt + random.uniform(0, 1)
            logger.warning(f"Discord API error during initialization (attempt {attempt}/{max_retries}): {e}")
            
            if attempt < max_retries:
                logger.info(f"Retrying initialization in {retry_delay:.2f} seconds...")
                await asyncio.sleep(retry_delay)
            else:
                logger.error("Maximum retries reached. Initialization failed.")
                
        except Exception as e:
            logger.exception(f"Unexpected error during initialization: {e}")
            # Do not mark as initialized here to allow retries

    # If initialization fails completely, log an error and do not mark as initialized
    if not bot.is_initialized:
        logger.critical("Bot failed to initialize after maximum retries. Manual intervention required.")


# ╔═════════════════════════════════════════════════════════════╗
# ║ 🔌 on_disconnect                                            ║
# ║ Called when the bot disconnects from Discord                ║
# ╚═════════════════════════════════════════════════════════════╝
@bot.event
async def on_disconnect():
    logger.warning("Bot disconnected from Discord. Waiting for reconnection...")


# ╔═════════════════════════════════════════════════════════════╗
# ║ 🔌 on_resumed                                               ║
# ║ Called when the bot reconnects after a disconnect           ║
# ╚═════════════════════════════════════════════════════════════╝
@bot.event
async def on_resumed():
    logger.info("Bot connection resumed")


# ╔═════════════════════════════════════════════════════════════╗
# ║ 📜 /herald                                                   ║
# ║ Posts the weekly + daily event summaries for all tags       ║
# ╚═════════════════════════════════════════════════════════════╝
@bot.tree.command(
    name="herald",
    description="Get a summary of all users' weekly and daily events"
)
async def herald_command(interaction: discord.Interaction):
    try:
        await interaction.response.defer(ephemeral=True)  # Make the response ephemeral
        today = get_today()
        monday = get_monday_of_week(today)
        
        # Create overall message to invoking user
        weekly_message_parts = []
        daily_message_parts = []
        errors = []  # Track errors for partial failures
        
        # Collect weekly data for all users
        for user_id in GROUPED_CALENDARS:
            try:
                user_name = TAG_NAMES.get(user_id, "Unknown User")
                user_mention = f"<@{user_id}>"
                
                # Get weekly events for this user
                events_by_day = defaultdict(list)
                calendars = GROUPED_CALENDARS.get(user_id)
                
                if not calendars:
                    continue
                    
                for meta in calendars:
                    try:
                        events = get_events(meta, monday, monday + timedelta(days=6))
                        if not events:
                            continue
                        for e in events:
                            start_date = datetime.fromisoformat(e["start"].get("dateTime", e["start"].get("date"))).date()
                            events_by_day[start_date].append(e)
                    except Exception as e:
                        logger.warning(f"Error getting events for calendar {meta['name']} (user {user_id}): {e}")
                
                if not events_by_day:
                    continue
                    
                # Add section for this user's weekly events
                user_weekly = [f"\n## 📆 **{user_mention}'s Weekly Events**\n"]
                
                for i in range(7):
                    day = monday + timedelta(days=i)
                    day_events = events_by_day.get(day, [])
                    if not day_events:
                        continue
                        
                    user_weekly.append(f"### 📅 **{day.strftime('%A, %B %d')}**")
                    for e in sorted(day_events, key=lambda e: e["start"].get("dateTime", e["start"].get("date"))):
                        start_time = e["start"].get("dateTime", e["start"].get("date"))
                        end_time = e["end"].get("dateTime", e["end"].get("date"))
                        summary = e.get("summary", "No Title")
                        location = e.get("location", "No Location")
                        
                        # Process mentions in event summary
                        for uid, name in TAG_NAMES.items():
                            if name in summary:
                                summary = summary.replace(f"@{name}", f"<@{uid}>")
                                summary = summary.replace(name, f"<@{uid}>")
                        
                        user_weekly.append(f"```{summary}\nTime: {start_time} - {end_time}\nLocation: {location}```")
                
                weekly_message_parts.append("\n".join(user_weekly))
                
                # Get daily events for this user
                events_by_source = defaultdict(list)
                for meta in calendars:
                    try:
                        events = get_events(meta, today, today)
                        if not events:
                            continue
                        for e in events:
                            events_by_source[meta["name"]].append(e)
                    except Exception as e:
                        logger.warning(f"Error getting events for {meta['name']} (user {user_id}): {e}")
                
                if not events_by_source:
                    continue
                    
                # Add section for this user's daily events
                user_daily = [f"\n## 🗓️ **{user_mention}'s Events Today ({today.strftime('%A, %B %d')})**\n"]
                
                for source_name, events in sorted(events_by_source.items()):
                    if not events:
                        continue
                    user_daily.append(f"**{source_name}**")
                    for e in sorted(events, key=lambda e: e["start"].get("dateTime", e["start"].get("date"))):
                        start_time = e["start"].get("dateTime", e["start"].get("date"))
                        end_time = e["end"].get("dateTime", e["end"].get("date"))
                        summary = e.get("summary", "No Title")
                        
                        # Process mentions in event summary
                        for uid, name in TAG_NAMES.items():
                            if name in summary:
                                summary = summary.replace(f"@{name}", f"<@{uid}>")
                                summary = summary.replace(name, f"<@{uid}>")
                        
                        location = e.get("location", "No Location")
                        user_daily.append(f"```{summary}\nTime: {start_time} - {end_time}\nLocation: {location}```")
                
                daily_message_parts.append("\n".join(user_daily))
            except Exception as e:
                logger.error(f"Error processing user {user_id}: {e}")
                errors.append(f"User {user_id}: {e}")
        
        # Combine and send all weekly messages first
        if weekly_message_parts:
            weekly_header = "# 📜 **Weekly Events Summary**\n"
            weekly_chunks = [weekly_header]
            current_chunk = weekly_header
            
            for part in weekly_message_parts:
                if len(current_chunk) + len(part) > 1900:
                    weekly_chunks.append(current_chunk)
                    current_chunk = part
                else:
                    current_chunk += part
            
            if current_chunk != weekly_header:
                weekly_chunks.append(current_chunk)
            
            # Send all weekly chunks
            for chunk in weekly_chunks[1:]:
                await interaction.followup.send(chunk, ephemeral=True)  # Send as ephemeral messages
        
        # Then send all daily messages
        if daily_message_parts:
            daily_header = "# 🗓️ **Today's Events Summary**\n"
            daily_chunks = [daily_header]
            current_chunk = daily_header
            
            for part in daily_message_parts:
                if len(current_chunk) + len(part) > 1900:
                    daily_chunks.append(current_chunk)
                    current_chunk = part
                else:
                    current_chunk += part
            
            if current_chunk != daily_header:
                daily_chunks.append(current_chunk)
            
            # Send all daily chunks
            for chunk in daily_chunks[1:]:
                await interaction.followup.send(chunk, ephemeral=True)  # Send as ephemeral messages
        
        # Report errors if any
        if errors:
            error_message = "\n".join(errors)
            await interaction.followup.send(
                f"⚠️ Some errors occurred while processing:\n```{error_message}```",
                ephemeral=True
            )
        
        # Confirmation message
        await interaction.followup.send("Herald events for all users have been sent.", ephemeral=True)
    except Exception as e:
        logger.exception(f"Error in /herald command: {e}")
        await interaction.followup.send("An error occurred while posting the herald.", ephemeral=True)


# ╔═════════════════════════════════════════════════════════════╗
# ║ 🔍 Autocomplete Functions                                    ║
# ║ Provides suggestions for command arguments                   ║
# ╚═════════════════════════════════════════════════════════════╝
async def autocomplete_agenda_input(
    interaction: discord.Interaction,
    current: str,
) -> List[app_commands.Choice[str]]:
    """Provides autocomplete for date input in agenda command."""
    suggestions = [
        "today", "tomorrow", "week", 
        "next monday", "next tuesday", "next wednesday", 
        "next thursday", "next friday", "next saturday", "next sunday"
    ]
    
    # Add suggestions for upcoming days of the week
    today = get_today()
    for i in range(1, 7):
        day = (today + datetime.timedelta(days=i)).strftime("%A").lower()
        if day not in suggestions:
            suggestions.append(day)
    
    # Filter based on current input
    if current:
        return [
            app_commands.Choice(name=suggestion, value=suggestion)
            for suggestion in suggestions if current.lower() in suggestion.lower()
        ][:25]
    
    # Return top suggestions if no input
    return [app_commands.Choice(name=suggestion, value=suggestion) for suggestion in suggestions[:25]]

async def autocomplete_agenda_target(
    interaction: discord.Interaction,
    current: str,
) -> List[app_commands.Choice[str]]:
    """Provides autocomplete for tag/user in agenda command."""
    suggestions = []
    
    # Add all tag names
    for tag in GROUPED_CALENDARS:
        display_name = TAG_NAMES.get(tag, tag)
        suggestions.append((display_name, display_name))
        # Also add the raw tag as an option
        if tag != display_name:
            suggestions.append((tag, tag))
    
    # Filter based on current input
    if current:
        filtered = [
            app_commands.Choice(name=name, value=value)
            for name, value in suggestions 
            if current.lower() in name.lower()
        ]
        return filtered[:25]  # Discord limits to 25 choices
    
    # Return all suggestions if no input
    return [app_commands.Choice(name=name, value=value) for name, value in suggestions[:25]]


# ╔═════════════════════════════════════════════════════════════╗
# ║ 🔗 resolve_tag_mappings                                      ║
# ║ Assigns display names and colors to tags based on members   ║
# ╚═════════════════════════════════════════════════════════════╝
async def resolve_tag_mappings():
    """Resolve user mappings and populate display names."""
    from events import GROUPED_CALENDARS

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


# ╔═════════════════════════════════════════════════════════════════╗
# ║ 🧩 Setup UI Components                                          ║
# ║ Interactive components for the setup process                    ║
# ╚═════════════════════════════════════════════════════════════════╝

class CalendarSetupView(View):
    """Main view for the calendar setup wizard."""
    def __init__(self, bot, guild_id):
        super().__init__(timeout=300)  # 5 minute timeout
        self.bot = bot
        self.guild_id = guild_id
        
    @discord.ui.button(label="Add Calendar", style=discord.ButtonStyle.primary, emoji="➕")
    async def add_calendar_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Launch the add calendar modal when this button is clicked."""
        modal = AddCalendarModal(self.bot, self.guild_id)
        await interaction.response.send_modal(modal)
        
    @discord.ui.button(label="Remove Calendar", style=discord.ButtonStyle.danger, emoji="🗑️")
    async def remove_calendar_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Show a dropdown of calendars that can be removed."""
        # Load server config to get list of calendars
        config = load_server_config(self.guild_id)
        calendars = config.get("calendars", [])
        
        if not calendars:
            await interaction.response.send_message("No calendars configured for this server yet.", ephemeral=True)
            return
            
        # Create dropdown for calendar selection
        view = CalendarRemoveView(self.bot, self.guild_id, calendars)
        await interaction.response.send_message(
            "Select the calendar you want to remove:", 
            view=view, 
            ephemeral=True
        )
        
    @discord.ui.button(label="List Calendars", style=discord.ButtonStyle.secondary, emoji="📋")
    async def list_calendars_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """List all configured calendars."""
        await interaction.response.defer(ephemeral=True)
        config = load_server_config(self.guild_id)
        calendars = config.get("calendars", [])
        
        if not calendars:
            await interaction.followup.send(
                "No calendars configured for this server yet. Click 'Add Calendar' to get started.",
                ephemeral=True
            )
            return
            
        # Format calendar list
        lines = ["**Configured Calendars:**\n"]
        
        for i, cal in enumerate(calendars, 1):
            cal_name = cal.get("name", "Unnamed Calendar")
            cal_id = cal.get("id", "unknown")
            cal_tag = cal.get("tag", "No Tag")
            user_id = cal.get("user_id", "Unknown User ID")
            user_name = TAG_NAMES.get(user_id, "Unknown User")
            
            # Truncate long calendar IDs
            display_id = cal_id[:27] + "..." if len(cal_id) > 30 else cal_id
                
            lines.append(
                f"{i}. **{cal_name}**\n"
                f"   ID: `{display_id}`\n"
                f"   User: **{user_name}** (ID: `{user_id}`)\n"
                f"   Tag: `{cal_tag}`"
            )
        
        await interaction.followup.send("\n".join(lines), ephemeral=True)
