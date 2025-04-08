"""
commands.py: Implements the slash commands for greeting, heralding, and agendas,
plus utilities for sending embeds to a predefined announcement channel.
"""

import os
import asyncio
import random
import dateparser  # Add missing import
from datetime import datetime, timedelta
from dateutil import tz
import discord
from discord import app_commands, errors as discord_errors
from collections import defaultdict
from typing import List  # Add this import for type hints

from events import (
    GROUPED_CALENDARS,
    get_events,
    get_name_for_tag,
    get_color_for_tag,
    TAG_NAMES
)
from utils import format_event  # Add missing import
from log import logger
from ai import generate_greeting, generate_image  # Fix function references


# ╔════════════════════════════════════════════════════════════════════╗
# ║ 🔍 Autocomplete Functions                                          ║
# ║ Provides suggestions for command arguments                         ║
# ╚════════════════════════════════════════════════════════════════════╝
async def autocomplete_tag(
    interaction: discord.Interaction, 
    current: str
) -> List[app_commands.Choice[str]]:
    """
    Provides autocomplete suggestions for user IDs.
    Used by commands that need to filter by user.
    """
    suggestions = []
    
    # Add all user IDs
    for user_id in GROUPED_CALENDARS:
        suggestions.append((user_id, user_id))
    
    # Filter based on current input
    if current:
        filtered = [
            app_commands.Choice(name=user_id, value=user_id)
            for user_id in suggestions 
            if current.lower() in user_id.lower()
        ]
        return filtered[:25]  # Discord limits to 25 choices
    
    # Return all suggestions if no input
    return [app_commands.Choice(name=user_id, value=user_id) for user_id in suggestions[:25]]

# ╔════════════════════════════════════════════════════════════════════╗
# ║ 🔄 _retry_discord_operation                                        ║
# ║ Helper function to retry Discord API operations with backoff      ║
# ╚════════════════════════════════════════════════════════════════════╝
async def _retry_discord_operation(operation, max_retries=3):
    last_error = None
    
    for attempt in range(max_retries):
        try:
            return await operation()
        except discord_errors.Forbidden as e:
            # Permission errors should not be retried
            logger.error(f"Permission error during Discord operation: {e}")
            raise
        except (discord_errors.HTTPException, discord_errors.GatewayNotFound) as e:
            backoff = (2 ** attempt) + random.random()
            logger.warning(f"Discord API error (attempt {attempt+1}/{max_retries}): {e}")
            logger.info(f"Retrying in {backoff:.2f} seconds...")
            last_error = e
            await asyncio.sleep(backoff)
    
    # If we've exhausted all retries, raise the last error
    if last_error:
        raise last_error


# ╔════════════════════════════════════════════════════════════════════╗
# ║ 🔍 check_channel_permissions                                        ║
# ║ Verifies the bot has necessary permissions in the channel          ║
# ╚════════════════════════════════════════════════════════════════════╝
def check_channel_permissions(channel, bot_member):
    required_permissions = [
        "view_channel",
        "send_messages",
        "embed_links",
        "attach_files"
    ]
    
    missing = []
    permissions = channel.permissions_for(bot_member)
    
    for perm in required_permissions:
        if not getattr(permissions, perm, False):
            missing.append(perm)
    
    return not missing, missing


# ╔════════════════════════════════════════════════════════════════════╗
# ║ 📤 send_embed                                                      ║
# ║ Sends an embed to the announcement channel, optionally with image ║
# ╚════════════════════════════════════════════════════════════════════╝
async def send_embed(bot, embed: discord.Embed = None, title: str = "", description: str = "", color: int = 5814783, image_path: str | None = None, content: str = ""):
    try:
        if isinstance(embed, str):
            logger.warning("send_embed() received a string instead of an Embed. Converting values assuming misuse.")
            description = embed
            embed = None
            
        from environ import ANNOUNCEMENT_CHANNEL_ID
        if not ANNOUNCEMENT_CHANNEL_ID:
            logger.warning("ANNOUNCEMENT_CHANNEL_ID not set.")
            return
            
        # Get channel with retry
        channel = None
        for _ in range(2):  # Try twice in case of cache issues
            channel = bot.get_channel(ANNOUNCEMENT_CHANNEL_ID)
            if channel:
                break
            # If not found in cache, try to fetch it
            try:
                channel = await bot.fetch_channel(ANNOUNCEMENT_CHANNEL_ID)
                break
            except Exception as e:
                logger.warning(f"Error fetching channel: {e}")
                await asyncio.sleep(1)
        
        if not channel:
            logger.error("Channel not found. Check ANNOUNCEMENT_CHANNEL_ID.")
            return
            
        # Check permissions
        bot_member = channel.guild.get_member(bot.user.id)
        has_permissions, missing_perms = check_channel_permissions(channel, bot_member)
        
        if not has_permissions:
            logger.error(f"Missing permissions in channel {channel.name}: {', '.join(missing_perms)}")
            return
            
        # Create embed if none was provided
        if embed is None:
            embed = discord.Embed(title=title, description=description, color=color)
            
        # Check if embed is too large (Discord limit is 6000 characters)
        embed_size = len(embed.title) + len(embed.description or "")
        for field in embed.fields:
            embed_size += len(field.name) + len(field.value)
            
        if embed_size > 5900:  # Leave some buffer
            logger.warning(f"Embed exceeds Discord's size limit ({embed_size}/6000 chars). Splitting content.")
            
            # Create a new embed with just title and description
            main_embed = discord.Embed(title=embed.title, description=embed.description, color=embed.color)
            if embed.footer:
                main_embed.set_footer(text=embed.footer.text)
                
            # Send the main embed first
            await _retry_discord_operation(lambda: channel.send(content=content, embed=main_embed))
            
            # Then send fields as separate embeds, grouping a few fields per embed
            field_groups = []
            current_group = []
            current_size = 0
            
            for field in embed.fields:
                field_size = len(field.name) + len(field.value)
                if current_size + field_size > 4000:  # Conservative field size limit
                    field_groups.append(current_group)
                    current_group = [field]
                    current_size = field_size
                else:
                    current_group.append(field)
                    current_size += field_size
                    
            if current_group:
                field_groups.append(current_group)
                
            for i, group in enumerate(field_groups):
                continuation_embed = discord.Embed(color=embed.color)
                if i < len(field_groups) - 1:
                    continuation_embed.set_footer(text=f"Continued ({i+1}/{len(field_groups)})")
                else:
                    if embed.footer:
                        continuation_embed.set_footer(text=embed.footer.text)
                        
                for field in group:
                    continuation_embed.add_field(name=field.name, value=field.value, inline=field.inline)
                    
                await _retry_discord_operation(lambda: channel.send(content=content, embed=continuation_embed))
                
            return
            
        # Process image if provided
        file = None
        if image_path and os.path.exists(image_path):
            try:
                file = discord.File(image_path, filename="image.png")
                embed.set_image(url="attachment://image.png")
            except Exception as e:
                logger.warning(f"Failed to load image from {image_path}: {e}")
                # Continue without the image
        
        # Send the message with retry
        if file:
            await _retry_discord_operation(lambda: channel.send(content=content, embed=embed, file=file))
        else:
            await _retry_discord_operation(lambda: channel.send(content=content, embed=embed))
            
    except Exception as e:
        logger.exception(f"Error in send_embed: {e}")


# ╔════════════════════════════════════════════════════════════════════╗
# ║ 📅 post_tagged_events                                              ║
# ║ Sends an embed of events for a specific tag on a given day        ║
# ║ Returns True if events were posted, False otherwise               ║
# ╚════════════════════════════════════════════════════════════════════╝
async def post_tagged_events(bot, user_id: str, day: datetime.date) -> bool:
    try:
        calendars = GROUPED_CALENDARS.get(user_id)
        if not calendars:
            logger.warning(f"No calendars found for user ID: {user_id}")
            return False

        events_by_source = defaultdict(list)
        for meta in calendars:
            try:
                events = get_events(meta, day, day)
                if not events:
                    events = []
                for e in events:
                    events_by_source[meta["name"]].append(e)
            except Exception as e:
                logger.exception(f"Error getting events for {meta['name']}: {e}")
                # Continue with other calendars even if one fails

        if not events_by_source:
            logger.debug(f"Skipping {user_id} — no events for {day}")
            return False

        # Construct plain text message
        message_lines = [f"🗓️ **Today's Events for {day.strftime('%A, %B %d')}**"]
        for source_name, events in sorted(events_by_source.items()):
            if not events:
                continue

            message_lines.append(f"\n📖 **{source_name}**")
            for e in sorted(events, key=lambda e: e["start"].get("dateTime", e["start"].get("date"))):
                message_lines.append(f" {format_event(e)}")

        # Send the message to the user
        user = await bot.fetch_user(user_id)
        await user.send("\n".join(message_lines))
        return True

    except Exception as e:
        logger.exception(f"Error in post_tagged_events for user ID {user_id} on {day}: {e}")
        return False


# ╔════════════════════════════════════════════════════════════════════╗
# 📅 /herald [tag] — Posts today's events for a calendar tag
# ╚════════════════════════════════════════════════════════════════════╝
async def post_tagged_week(bot, user_id: str, monday: datetime.date):
    try:
        events_by_day = defaultdict(list)
        calendars = GROUPED_CALENDARS.get(user_id)
        if not calendars:
            logger.warning(f"No calendars found for user ID: {user_id}")
            return

        for meta in calendars:
            try:
                events = get_events(meta, monday, monday + timedelta(days=6))
                if not events:
                    events = []
                for e in events:
                    start_str = e["start"].get("dateTime", e["start"].get("date"))
                    end_str = e["end"].get("dateTime", e["end"].get("date"))
                    start_date = datetime.fromisoformat(start_str.replace("Z", "+00:00")).date()
                    end_date = datetime.fromisoformat(end_str.replace("Z", "+00:00")).date() if end_str else None

                    if start_date and end_date and start_date != end_date:
                        # Add multi-day events to all relevant days
                        current_date = start_date
                        while current_date <= end_date:
                            events_by_day[current_date].append(e)
                            current_date += timedelta(days=1)
                    elif start_date:
                        events_by_day[start_date].append(e)
            except Exception as e:
                logger.exception(f"Error getting events for calendar {meta['name']}: {e}")

        # Construct plain text message
        message_lines = [f"📜 **Weekly Events for the Week of {monday.strftime('%B %d')}**"]
        for i in range(7):
            day = monday + timedelta(days=i)
            day_events = events_by_day.get(day, [])
            if not day_events:
                continue

            message_lines.append(f"\n📅 **{day.strftime('%A')}**")
            for e in sorted(day_events, key=lambda e: e["start"].get("dateTime", e["start"].get("date"))):
                message_lines.append(f" {format_event(e)}")

        # Send the message to the user
        user = await bot.fetch_user(user_id)
        await user.send("\n".join(message_lines))

    except Exception as e:
        logger.exception(f"Error in post_tagged_week for user ID {user_id}: {e}")


# ╔════════════════════════════════════════════════════════════════════╗
# 📅 /agenda [date] — Returns events for a specific date
# ╚════════════════════════════════════════════════════════════════════╝
@app_commands.command(name="agenda", description="See events for a specific date (natural language supported)")
@app_commands.describe(date="Examples: today, tomorrow, next Thursday")
async def agenda(interaction: discord.Interaction, date: str) -> None:
    await interaction.response.defer()
    logger.info(f"[commands.py] 📅 /agenda called by {interaction.user} with date '{date}'")

    try:
        dt = dateparser.parse(date)
        if not dt:
            await interaction.followup.send("⚠️ Could not understand that date.")
            return

        day = dt.date()
        all_events = []
        for user_id, sources in GROUPED_CALENDARS.items():
            for source in sources:
                events = await interaction.client.loop.run_in_executor(None, get_events, source, day, day)
                all_events.extend(events)

        # Sort by start time
        all_events.sort(key=lambda e: e["start"].get("dateTime", e["start"].get("date")))

        if not all_events:
            await interaction.followup.send(f"No events found for `{date}`.")
            return

        # Construct plain text message
        message_lines = [f"🗓️ **Agenda for {interaction.user.display_name} on {day.strftime('%A, %d %B %Y')}**"]
        for e in all_events:
            message_lines.append(f" {format_event(e)}")

        # Send the message to the user
        await interaction.user.send("\n".join(message_lines))
        await interaction.followup.send("Agenda sent to your DMs.")

    except Exception as e:
        logger.exception("[commands.py] Error in /agenda command.", exc_info=e)
        await interaction.followup.send("⚠️ An error occurred while fetching the agenda.")
