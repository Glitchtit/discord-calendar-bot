import os
import asyncio
import random
from datetime import datetime, timedelta
from dateutil import tz
import discord # type: ignore
from discord import app_commands, errors as discord_errors # type: ignore
from collections import defaultdict

from events import (
    GROUPED_CALENDARS,
    get_events,
    get_name_for_tag,
    get_color_for_tag,
    TAG_NAMES
)
from log import logger
from utils import format_event, resolve_input_to_tags
from resilience import async_retry_with_backoff
from views import (
    build_event_pages,
    build_week_pages,
    PaginatedEmbedView,
)


# ╔════════════════════════════════════════════════════════════════════╗
# ║ 🔄 _retry_discord_operation                                        ║
# ║ Helper function to retry Discord API operations with backoff      ║
# ╚════════════════════════════════════════════════════════════════════╝
async def _retry_discord_operation(operation, max_retries=3):
    return await async_retry_with_backoff(
        operation,
        max_retries=max_retries,
        non_retryable=(discord_errors.Forbidden,),
    )


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
async def send_embed(bot, embed: discord.Embed = None, title: str = "", description: str = "", color: int = 5814783, image_path: str | None = None, view: discord.ui.View | None = None):
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
            await _retry_discord_operation(lambda: channel.send(embed=main_embed))
            
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
                    
                await _retry_discord_operation(lambda: channel.send(embed=continuation_embed))
                
            return
            
        # Process image if provided
        file = None
        if image_path and os.path.exists(image_path):
            try:
                file = discord.File(image_path, filename="image.png")
                embed.set_image(url="attachment://image.png")
            except Exception as e:
                logger.warning(f"Failed to load image from {image_path}: {e}")
        
        # Send the message with retry
        kwargs: dict = {"embed": embed}
        if file:
            kwargs["file"] = file
        if view is not None:
            kwargs["view"] = view
        msg = await _retry_discord_operation(lambda: channel.send(**kwargs))

        # Store message reference so View can disable buttons on timeout
        if view is not None and hasattr(view, "message") and msg:
            view.message = msg
            
    except Exception as e:
        logger.exception(f"Error in send_embed: {e}")


# ╔════════════════════════════════════════════════════════════════════╗
# ║ 📅 post_tagged_events                                              ║
# ║ Sends an embed of events for a specific tag on a given day        ║
# ║ Returns True if events were posted, False otherwise               ║
# ╚════════════════════════════════════════════════════════════════════╝
async def post_tagged_events(bot, tag: str, day: datetime.date) -> bool:
    try:
        calendars = GROUPED_CALENDARS.get(tag)
        if not calendars:
            logger.warning(f"No calendars found for tag: {tag}")
            return False

        events_by_source = defaultdict(list)
        all_events = []
        
        for meta in calendars:
            try:
                events = get_events(meta, day, day)
                all_events.extend([(meta["name"], e) for e in events])
            except Exception as e:
                logger.exception(f"Error getting events for {meta['name']}: {e}")

        for source_name, event in all_events:
            start_str = event["start"].get("dateTime", event["start"].get("date"))
            dt = datetime.fromisoformat(start_str.replace("Z", "+00:00")) if "T" in start_str else datetime.fromisoformat(start_str)
            event_date = dt.date()
            if event_date == day:
                events_by_source[source_name].append(event)

        if not events_by_source:
            logger.debug(f"Skipping {tag} — no events for {day}")
            return False

        pages, epp = build_event_pages(
            events_by_source,
            title=f"🗓️ Herald's Scroll — {get_name_for_tag(tag)}",
            description=f"Events for **{day.strftime('%A, %B %d')}**",
            color=get_color_for_tag(tag),
        )
        view = PaginatedEmbedView(pages, epp)
        await send_embed(bot, embed=pages[0], view=view)
        return True
        
    except Exception as e:
        logger.exception(f"Error in post_tagged_events for tag {tag} on {day}: {e}")
        return False


# ╔════════════════════════════════════════════════════════════════════╗
# ║ 📆 post_tagged_week                                                ║
# ║ Sends an embed of the weekly schedule for a given calendar tag    ║
# ╚════════════════════════════════════════════════════════════════════╝
async def post_tagged_week(bot, tag: str, monday: datetime.date):
    try:
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

        pages, epp = build_week_pages(
            events_by_day,
            title=f"📜 Herald’s Week — {get_name_for_tag(tag)}",
            description=f"Week of **{monday.strftime('%B %d')}**",
            color=get_color_for_tag(tag),
            monday=monday,
        )
        view = PaginatedEmbedView(pages, epp)
        await send_embed(bot, embed=pages[0], view=view)
    except Exception as e:
        logger.exception(f"Error in post_tagged_week for tag {tag} starting {monday}: {e}")


# ╔════════════════════════════════════════════════════════════════════╗
# ║ 🔍 Autocomplete Functions for Slash Commands                       ║
# ║ Provide dynamic suggestions in Discord UI                         ║
# ╚════════════════════════════════════════════════════════════════════╝

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


# ╔════════════════════════════════════════════════════════════════════╗
# ║ 🔎 search_events                                                   ║
# ║ Search calendar events by keyword across titles and descriptions  ║
# ╚════════════════════════════════════════════════════════════════════╝
async def search_events(
    query: str,
    days_ahead: int = 30,
    tag: str | None = None,
) -> tuple[list[discord.Embed], list[list[dict]]]:
    """Search upcoming events matching *query*. Returns paginated pages."""
    from utils import get_today, parse_date_string, get_local_timezone

    today = get_today()
    end = today + timedelta(days=days_ahead)
    matches: list[dict] = []
    q = query.lower()

    tags = [tag] if tag and tag in GROUPED_CALENDARS else list(GROUPED_CALENDARS.keys())

    for t in tags:
        for meta in GROUPED_CALENDARS.get(t, []):
            try:
                events = await asyncio.to_thread(get_events, meta, today, end)
                for ev in events:
                    title = (ev.get("summary") or "").lower()
                    orig = (ev.get("original_summary") or "").lower()
                    desc = (ev.get("description") or "").lower()
                    if q in title or q in orig or q in desc:
                        ev["_search_tag"] = t
                        matches.append(ev)
            except Exception as e:
                logger.debug(f"Search: error fetching {meta.get('name')}: {e}")

    matches.sort(key=lambda e: e["start"].get("dateTime", e["start"].get("date", "")))

    if not matches:
        embed = discord.Embed(
            title=f"🔎 No results for \"{query}\"",
            description=f"No events matching **{query}** in the next {days_ahead} days.",
            color=0x95A5A6,
        )
        return [embed], [[]]

    # Group by date for a clean display
    local_tz = get_local_timezone()
    events_by_day: dict = defaultdict(list)
    for ev in matches:
        start_str = ev["start"].get("dateTime", ev["start"].get("date", ""))
        dt = parse_date_string(start_str, local_tz)
        if dt:
            events_by_day[dt.date()].append(ev)

    pages, epp = build_week_pages(
        events_by_day,
        title=f"🔎 Results for \"{query}\"",
        description=f"{len(matches)} event{'s' if len(matches) != 1 else ''} in the next {days_ahead} days",
        color=0x3498DB,
        monday=None,
    )
    return pages, epp
