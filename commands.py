"""
commands.py: Implements the slash commands for greeting, heralding, and agendas,
plus utilities for sending embeds to a predefined announcement channel.
"""

import os
from typing import List, Optional

import discord
from discord import app_commands, Interaction
from discord.ext.commands import Bot

import dateparser

from events import GROUPED_CALENDARS, get_events, get_name_for_tag, get_color_for_tag
from utils import format_event, get_today
from log import logger
from ai import generate_greeting_text, generate_greeting_image


# ╔════════════════════════════════════════════════════════════════════╗
# 📤 Helper Function: send_embed
# ╚════════════════════════════════════════════════════════════════════╝
async def send_embed(
    bot: Bot,
    embed: Optional[discord.Embed] = None,
    title: str = "",
    description: str = "",
    color: int = 0x58B9FF,
    image_path: Optional[str] = None
) -> None:
    """
    Sends a Discord embed (with optional attached image) to the configured
    announcement channel. If the channel or image is not found, logs a warning.

    Args:
        bot: The instance of discord.ext.commands.Bot.
        embed: A preconstructed Embed object, or None if creating a new embed.
        title: The title of the embed (used if embed is None).
        description: The description text for the embed (used if embed is None).
        color: Integer color code for the embed border (used if embed is None).
        image_path: Filesystem path to an image to attach.

    Returns:
        None
    """
    from environ import ANNOUNCEMENT_CHANNEL_ID  # to avoid circular import
    if not ANNOUNCEMENT_CHANNEL_ID:
        logger.warning("[commands.py] ANNOUNCEMENT_CHANNEL_ID is not set.")
        return

    channel = bot.get_channel(ANNOUNCEMENT_CHANNEL_ID)
    if channel is None:
        logger.error("[commands.py] Announcement channel not found. Check ANNOUNCEMENT_CHANNEL_ID.")
        return

    # If the caller didn't supply an embed, build a new one
    if embed is None:
        embed = discord.Embed(title=title, description=description, color=color)

    # If an image path is specified, attach the image
    if image_path and os.path.exists(image_path):
        file = discord.File(image_path, filename="image.png")
        embed.set_image(url="attachment://image.png")
        await channel.send(embed=embed, file=file)
    else:
        await channel.send(embed=embed)


# ╔════════════════════════════════════════════════════════════════════╗
# 🎨 /greet — AI Greeting Command
# ╚════════════════════════════════════════════════════════════════════╝
@app_commands.command(name="greet2", description="Post an AI-generated greeting with today's schedule")
async def greet(interaction: discord.Interaction) -> None:
    """
    Generates an AI-based greeting text and image, then sends them as
    an embed to the announcement channel.

    Usage: /greet
    """
    await interaction.response.defer()
    logger.info(f"[commands.py] 🎨 Generating AI greeting for user {interaction.user}.")

    try:
        # Generate greeting text
        greeting_text: str = await generate_greeting_text()

        # Generate AI image
        image_path: Optional[str] = await generate_greeting_image(greeting_text)

        # Send embed with greeting
        await send_embed(
            bot=interaction.client,  # "interaction.client" is our Bot instance
            title="📣 Daily AI Greeting",
            description=greeting_text,
            image_path=image_path
        )
        logger.info("[commands.py] ✅ AI greeting posted successfully.")

    except Exception as e:
        logger.exception("[commands.py] Error in /greet command.", exc_info=e)
        await interaction.followup.send("⚠️ An error occurred while generating the greeting.")


# ╔════════════════════════════════════════════════════════════════════╗
# 👥 Async Autocomplete for the Herald Command
# ╚════════════════════════════════════════════════════════════════════╝
async def herald_tag_autocomplete(
    interaction: Interaction,
    current: str
) -> List[app_commands.Choice[str]]:
    """
    Provides autocomplete suggestions for the tag parameter of /herald.
    Suggests tags that start with the current input, or all tags if input is empty.

    Args:
        interaction: The current Interaction (not used in logic, but required by signature).
        current: The user’s partial input in the slash command.

    Returns:
        A list of Choice objects for the user to pick from.
    """
    return [
        app_commands.Choice(name=tag, value=tag)
        for tag in sorted(GROUPED_CALENDARS)
        if tag.startswith(current.upper()) or current == ""
    ]


# ╔════════════════════════════════════════════════════════════════════╗
# 📅 /herald [tag] — Posts today's events for a calendar tag
# ╚════════════════════════════════════════════════════════════════════╝
@app_commands.command(name="herald2", description="Post today's events for a calendar tag")
@app_commands.describe(tag="Tag name (e.g., A, B, T)")
@app_commands.autocomplete(tag=herald_tag_autocomplete)
async def herald(interaction: discord.Interaction, tag: str) -> None:
    """
    Fetches today's events for a specific calendar tag (e.g., 'A', 'B', etc.)
    and sends them as an embed to the announcement channel.

    Usage: /herald <tag>
    """
    await interaction.response.defer()
    logger.info(f"[commands.py] 📣 /herald called by {interaction.user} for tag '{tag}'")

    try:
        today = get_today()
        all_events = []
        for source in GROUPED_CALENDARS.get(tag.upper(), []):
            events = await interaction.client.loop.run_in_executor(None, get_events, source, today, today)
            all_events.extend(events)

        # Sort by start time
        all_events.sort(key=lambda e: e["start"].get("dateTime", e["start"].get("date")))

        if not all_events:
            await interaction.followup.send(f"⚠️ No events found today for tag `{tag}`.")
            return

        embed = discord.Embed(
            title=f"📅 Today’s Events — {get_name_for_tag(tag)}",
            color=get_color_for_tag(tag),
            description="\n\n".join(format_event(e) for e in all_events)
        )
        embed.set_footer(text=f"{len(all_events)} event(s) • {today.strftime('%A, %d %B %Y')}")

        # Use our send_embed helper
        await send_embed(bot=interaction.client, embed=embed)
        logger.info("[commands.py] ✅ Herald command posted events successfully.")

    except Exception as e:
        logger.exception("[commands.py] Error in /herald command.", exc_info=e)
        await interaction.followup.send("⚠️ An error occurred while fetching today's events.")


# ╔════════════════════════════════════════════════════════════════════╗
# 📅 /agenda [date] — Returns events for a specific date
# ╚════════════════════════════════════════════════════════════════════╝
@app_commands.command(name="agenda2", description="See events for a specific date (natural language supported)")
@app_commands.describe(date="Examples: today, tomorrow, next Thursday")
async def agenda(interaction: discord.Interaction, date: str) -> None:
    """
    Accepts a natural-language date string, resolves it to a day, and
    fetches all events from all calendar tags for that day.

    Usage: /agenda <natural-language-date>
    """
    await interaction.response.defer()
    logger.info(f"[commands.py] 📅 /agenda called by {interaction.user} with date '{date}'")

    try:
        dt = dateparser.parse(date)
        if not dt:
            await interaction.followup.send("⚠️ Could not understand that date.")
            return

        day = dt.date()
        all_events = []
        for tag, sources in GROUPED_CALENDARS.items():
            for source in sources:
                events = await interaction.client.loop.run_in_executor(None, get_events, source, day, day)
                all_events.extend(events)

        # Sort by start time
        all_events.sort(key=lambda e: e["start"].get("dateTime", e["start"].get("date")))

        if not all_events:
            await interaction.followup.send(f"No events found for `{date}`.")
            return

        embed = discord.Embed(
            title=f"🗓️ Agenda for {day.strftime('%A, %d %B %Y')}",
            color=0x3498db,
            description="\n\n".join(format_event(e) for e in all_events)
        )
        embed.set_footer(text=f"{len(all_events)} event(s)")

        await send_embed(bot=interaction.client, embed=embed)
        logger.info("[commands.py] ✅ Agenda command posted events successfully.")

    except Exception as e:
        logger.exception("[commands.py] Error in /agenda command.", exc_info=e)
        await interaction.followup.send("⚠️ An error occurred while fetching the agenda.")
