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


class AddCalendarModal(Modal, title="Add Calendar"):
    """Modal form for adding a new calendar."""
    
    # Text inputs for the form
    calendar_url = TextInput(
        label="Calendar URL or ID",
        placeholder="Google Calendar ID or ICS URL",
        required=True,
        style=discord.TextStyle.short
    )
    
    display_name = TextInput(
        label="Calendar Display Name (Optional)",
        placeholder="e.g. 'Work Calendar' or 'Family Events'",
        required=False,
        style=discord.TextStyle.short
    )
    
    def __init__(self, bot, guild_id):
        super().__init__(timeout=300)  # 5 minute timeout
        self.bot = bot
        self.guild_id = guild_id
    
    async def on_submit(self, interaction: discord.Interaction):
        """Handle the form submission."""
        await interaction.response.defer(ephemeral=True)
        
        # Step 1: Validate the calendar URL
        calendar_url = self.calendar_url.value.strip()
        
        # Detect calendar type
        calendar_type = detect_calendar_type(calendar_url)
        if not calendar_type:
            await interaction.followup.send(
                "❌ Invalid calendar format. Please provide a valid Google Calendar ID or ICS URL.", 
                ephemeral=True
            )
            return
            
        # Step 2: Show user selection view
        # Create a select menu with guild members
        view = UserSelectView(self.bot, self.guild_id, calendar_url, self.display_name.value)
        
        if calendar_type == 'google':
            instructions = (
                f"**Google Calendar Detected**\n\n"
                f"After selecting a user, you'll need to share your Google Calendar with:\n"
                f"`{get_service_account_email()}`\n\n"
                f"**Select which user this calendar belongs to:**"
            )
        else:
            instructions = "**ICS Calendar Detected**\n\n**Select which user this calendar belongs to:**"
            
        await interaction.followup.send(instructions, view=view, ephemeral=True)


class UserSelectView(View):
    """View for selecting which user the calendar belongs to."""
    def __init__(self, bot, guild_id, calendar_url, display_name):
        super().__init__(timeout=300)  # 5 minute timeout
        self.bot = bot
        self.guild_id = guild_id
        self.calendar_url = calendar_url
        self.display_name = display_name
        self.page = 0  # Track the current page
        self.members = self.get_sorted_members()
        self.max_pages = (len(self.members) - 1) // 25 + 1

        # Create the initial dropdown
        self.update_dropdown()

    def get_sorted_members(self):
        """Get sorted list of guild members."""
        guild = self.bot.get_guild(self.guild_id)
        return sorted(
            [m for m in guild.members if not m.bot],
            key=lambda m: m.display_name.lower()
        )

    def update_dropdown(self):
        """Update the dropdown with the current page of members."""
        self.clear_items()
        start = self.page * 25
        end = start + 25
        members_page = self.members[start:end]

        select = Select(placeholder="Select a user...", min_values=1, max_values=1)
        for member in members_page:
            select.add_option(
                label=member.display_name,
                value=str(member.id),
                description=f"User ID: {member.id}"
            )
        select.callback = self.select_callback
        self.add_item(select)

        # Add navigation buttons if there are multiple pages
        if self.max_pages > 1:
            if self.page > 0:
                self.add_item(Button(label="Previous", style=discord.ButtonStyle.primary, custom_id="prev_page"))
            if self.page < self.max_pages - 1:
                self.add_item(Button(label="Next", style=discord.ButtonStyle.primary, custom_id="next_page"))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Handle navigation button clicks."""
        if interaction.data["custom_id"] == "prev_page":
            self.page -= 1
        elif interaction.data["custom_id"] == "next_page":
            self.page += 1
        self.update_dropdown()
        await interaction.response.edit_message(view=self)

    async def select_callback(self, interaction: discord.Interaction):
        """Handle user selection."""
        user_id = interaction.data["values"][0]
        user = self.bot.get_guild(self.guild_id).get_member(int(user_id))

        # If display name wasn't provided, use user's name + "Calendar"
        final_display_name = self.display_name or f"{user.display_name}'s Calendar"

        # Add the calendar
        success, message = add_calendar(
            self.guild_id,
            self.calendar_url,
            user_id,
            final_display_name
        )

        # Reload calendar configuration and reinitialize events
        try:
            await reinitialize_events()
        except Exception as e:
            logger.error(f"Error during reinitialization: {e}")

        # Show the result
        await interaction.response.send_message(
            f"{'✅' if success else '❌'} {message}",
            ephemeral=True
        )


class CalendarRemoveView(View):
    """View for selecting which calendar to remove."""
    def __init__(self, bot, guild_id, calendars):
        super().__init__(timeout=300)  # 5 minute timeout
        self.bot = bot
        self.guild_id = guild_id
        self.calendars = calendars
        self.page = 0  # Track the current page
        self.max_pages = (len(self.calendars) - 1) // 25 + 1

        # Create the initial dropdown
        self.update_dropdown()

    def update_dropdown(self):
        """Update the dropdown with the current page of calendars."""
        self.clear_items()
        start = self.page * 25
        end = start + 25
        calendars_page = self.calendars[start:end]

        select = Select(placeholder="Select calendar to remove...", min_values=1, max_values=1)
        for cal in calendars_page:
            cal_name = cal.get("name", "Unnamed Calendar")
            cal_id = cal.get("id", "unknown")
            display_id = cal_id[:20] + "..." + cal_id[-7:] if len(cal_id) > 30 else cal_id
            select.add_option(
                label=cal_name[:80] if len(cal_name) > 80 else cal_name,
                value=cal_id[:100] if len(cal_id) > 100 else cal_id,
                description=f"ID: {display_id}"
            )
        select.callback = self.select_callback
        self.add_item(select)

        # Add navigation buttons if there are multiple pages
        if self.max_pages > 1:
            if self.page > 0:
                self.add_item(Button(label="Previous", style=discord.ButtonStyle.primary, custom_id="prev_page"))
            if self.page < self.max_pages - 1:
                self.add_item(Button(label="Next", style=discord.ButtonStyle.primary, custom_id="next_page"))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Handle navigation button clicks."""
        if interaction.data["custom_id"] == "prev_page":
            self.page -= 1
        elif interaction.data["custom_id"] == "next_page":
            self.page += 1
        self.update_dropdown()
        await interaction.response.edit_message(view=self)

    async def select_callback(self, interaction: discord.Interaction):
        """Handle calendar selection for removal."""
        calendar_id = interaction.data["values"][0]

        # Add confirmation button
        confirm_view = ConfirmRemovalView(self.bot, self.guild_id, calendar_id)
        await interaction.response.send_message(
            f"Are you sure you want to remove this calendar?\n`{calendar_id}`",
            view=confirm_view,
            ephemeral=True
        )


class ConfirmRemovalView(View):
    """Confirmation view for calendar removal."""
    def __init__(self, bot, guild_id, calendar_id):
        super().__init__(timeout=60)  # Short timeout for confirmation
        self.bot = bot
        self.guild_id = guild_id
        self.calendar_id = calendar_id
        
    @discord.ui.button(label="Confirm Removal", style=discord.ButtonStyle.danger)
    async def confirm_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Remove the calendar when confirmed."""
        # Remove the calendar
        success, message = remove_calendar(self.guild_id, self.calendar_id)
        
        # Reload calendar configuration if successful and reinitialize events
        if success:
            try:
                await reinitialize_events()
            except Exception as e:
                logger.error(f"Error during reinitialization: {e}")
            
        await interaction.response.send_message(
            f"{'✅' if success else '❌'} {message}",
            ephemeral=True
        )
        
    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Cancel the removal."""
        await interaction.response.send_message("Calendar removal cancelled.", ephemeral=True)
        self.stop()
