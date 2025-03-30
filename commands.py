import os
from datetime import datetime, timedelta
from dateutil import tz
import discord
from discord import app_commands

from events import (
    GROUPED_CALENDARS,
    get_events,
    get_name_for_tag,
    get_color_for_tag,
    TAG_NAMES
)
from log import logger
from utils import format_event, resolve_input_to_tags


# ─────────────────────────────────────────────────────────────
# 📤 EMBED HANDLING
# ─────────────────────────────────────────────────────────────

async def send_embed(bot, title: str, description: str, color: int = 5814783, image_path: str | None = None):
    from environ import ANNOUNCEMENT_CHANNEL_ID
    if not ANNOUNCEMENT_CHANNEL_ID:
        logger.warning("ANNOUNCEMENT_CHANNEL_ID not set.")
        return
    channel = bot.get_channel(ANNOUNCEMENT_CHANNEL_ID)
    if not channel:
        logger.error("Channel not found. Check ANNOUNCEMENT_CHANNEL_ID.")
        return

    embed = discord.Embed(title=title, description=description, color=color)
    if image_path and os.path.exists(image_path):
        file = discord.File(image_path, filename="image.png")
        embed.set_image(url="attachment://image.png")
        await channel.send(embed=embed, file=file)
    else:
        await channel.send(embed=embed)


# ─────────────────────────────────────────────────────────────
# 📅 EVENT POSTING
# ─────────────────────────────────────────────────────────────

from collections import defaultdict
from discord import Embed

async def post_tagged_events(bot, tag: str, day: datetime.date):
    calendars = GROUPED_CALENDARS.get(tag)
    if not calendars:
        logger.warning(f"No calendars found for tag: {tag}")
        return

    events_by_source = defaultdict(list)
    for meta in calendars:
        events = get_events(meta, day, day)
        for e in events:
            events_by_source[meta["name"]].append(e)

    if not events_by_source:
        logger.debug(f"Skipping {tag} — no events for {day}")
        return

    embed = Embed(
        title=f"🗓️ Herald’s Scroll — {get_name_for_tag(tag)}",
        description=f"Events for **{day.strftime('%A, %B %d')}**",
        color=get_color_for_tag(tag)
    )

    for source_name, events in sorted(events_by_source.items()):
        if not events:
            continue
        lines = [format_event(e) for e in sorted(events, key=lambda e: e["start"].get("dateTime", e["start"].get("date")))]
        embed.add_field(name=f"📖 {source_name}", value="\n".join(lines), inline=False)

    embed.set_footer(text=f"Posted at {datetime.now().strftime('%H:%M %p')}")
    await send_embed(bot, embed=embed)



from collections import defaultdict
from discord import Embed

async def post_tagged_week(bot, tag: str, monday: datetime.date):
    calendars = GROUPED_CALENDARS.get(tag)
    if not calendars:
        logger.warning(f"No calendars for tag {tag}")
        return

    end = monday + timedelta(days=6)
    all_events = []
    for meta in calendars:
        all_events += get_events(meta, monday, end)

    if not all_events:
        logger.debug(f"Skipping {tag} — no weekly events from {monday} to {end}")
        return

    events_by_day = defaultdict(list)
    for e in all_events:
        start_str = e["start"].get("dateTime", e["start"].get("date"))
        dt = datetime.fromisoformat(start_str.replace("Z", "+00:00")) if "T" in start_str else datetime.fromisoformat(start_str)
        events_by_day[dt.date()].append(e)

    embed = Embed(
        title=f"📜 Herald’s Week — {get_name_for_tag(tag)}",
        description=f"Week of **{monday.strftime('%B %d')}**",
        color=get_color_for_tag(tag)
    )

    for i in range(7):
        day = monday + timedelta(days=i)
        day_events = events_by_day.get(day, [])
        if not day_events:
            continue
        lines = [format_event(e) for e in sorted(day_events, key=lambda e: e["start"].get("dateTime", e["start"].get("date")))]
        embed.add_field(name=f"📅 {day.strftime('%A')}", value="\n".join(lines), inline=False)

    embed.set_footer(text=f"Posted at {datetime.now().strftime('%H:%M %p')}")
    await send_embed(bot, embed=embed)



# ─────────────────────────────────────────────────────────────
# 🔍 AUTOCOMPLETE
# ─────────────────────────────────────────────────────────────

def get_known_tags():
    return list(GROUPED_CALENDARS.keys())


async def autocomplete_tag(interaction: discord.Interaction, current: str):
    return [
        app_commands.Choice(name=tag, value=tag)
        for tag in get_known_tags() if current.lower() in tag.lower()
    ]


async def autocomplete_range(interaction: discord.Interaction, current: str):
    return [
        app_commands.Choice(name=r, value=r)
        for r in ["today", "week"] if current.lower() in r
    ]


async def autocomplete_agenda_input(interaction: discord.Interaction, current: str):
    suggestions = ["today", "tomorrow", "week", "next monday", "this friday"]
    return [
        app_commands.Choice(name=s, value=s)
        for s in suggestions if current.lower() in s.lower()
    ]


async def autocomplete_agenda_target(interaction: discord.Interaction, current: str):
    suggestions = list(set(get_known_tags() + list(TAG_NAMES.values())))
    return [
        app_commands.Choice(name=s, value=s)
        for s in suggestions if current.lower() in s.lower()
    ][:25]
