from datetime import datetime, timedelta
from dateutil import tz
from discord.ext import tasks
import asyncio

from utils import (
    get_today,
    get_monday_of_week,
    is_in_current_week,
    format_event
)
from commands import (
    post_tagged_week,
    post_tagged_events,
    send_embed
)
from events import (
    GROUPED_CALENDARS,
    get_events,
    get_name_for_tag,
    get_color_for_tag,
    load_previous_events,
    save_current_events_for_key,
    compute_event_fingerprint
)
from log import logger
from ai import generate_greeting, generate_image


# ╔════════════════════════════════════════════════════════════════════╗
# ║ 🚀 start_all_tasks                                                 ║
# ║ Activates recurring task loops for scheduling and change watching ║
# ╚════════════════════════════════════════════════════════════════════╝
def start_all_tasks(bot):
    schedule_daily_posts.change_interval(minutes=1)
    watch_for_event_changes.change_interval(seconds=10)
    schedule_daily_posts.start(bot)
    watch_for_event_changes.start(bot)


# ╔════════════════════════════════════════════════════════════════════╗
# ║ ⏰ schedule_daily_posts                                            ║
# ║ Triggers daily and weekly posting tasks at scheduled times        ║
# ╚════════════════════════════════════════════════════════════════════╝
@tasks.loop(minutes=1)
async def schedule_daily_posts(bot):
    local_now = datetime.now(tz=tz.tzlocal())
    today = local_now.date()

    # Monday 08:00 — Post weekly summaries
    if local_now.weekday() == 0 and local_now.hour == 8 and local_now.minute == 0:
        monday = get_monday_of_week(today)
        for tag in GROUPED_CALENDARS:
            await post_tagged_week(bot, tag, monday)

    # Daily 08:01 — Post today’s agenda and greeting
    if local_now.hour == 8 and local_now.minute == 1:
        await post_todays_happenings(bot, include_greeting=True)


# ╔════════════════════════════════════════════════════════════════════╗
# ║ 🕵️ watch_for_event_changes                                        ║
# ║ Detects new or removed events in the current week and posts diffs ║
# ╚════════════════════════════════════════════════════════════════════╝
@tasks.loop(seconds=60)
async def watch_for_event_changes(bot):
    today = get_today()
    monday = get_monday_of_week(today)

    for tag, calendars in GROUPED_CALENDARS.items():
        earliest = today - timedelta(days=30)
        latest = today + timedelta(days=90)

        # Fetch and fingerprint all events in the date window
        all_events = []
        for meta in calendars:
            events = await asyncio.to_thread(get_events, meta, earliest, latest)
            all_events += events
        all_events.sort(key=lambda e: e["start"].get("dateTime", e["start"].get("date")))

        key = f"{tag}_full"
        prev_snapshot = load_previous_events().get(key, [])
        prev_fps = {compute_event_fingerprint(e): e for e in prev_snapshot}
        curr_fps = {compute_event_fingerprint(e): e for e in all_events}

        added = [e for fp, e in curr_fps.items() if fp not in prev_fps]
        removed = [e for fp, e in prev_fps.items() if fp not in curr_fps]

        # Limit notifications to events in this week
        added_week = [e for e in added if is_in_current_week(e, today)]
        removed_week = [e for e in removed if is_in_current_week(e, today)]

        if added_week or removed_week:
            lines = []
            if added_week:
                lines.append("**📥 Added Events This Week:**")
                lines += [f"➕ {format_event(e)}" for e in added_week]
            if removed_week:
                lines.append("**📤 Removed Events This Week:**")
                lines += [f"➖ {format_event(e)}" for e in removed_week]

            await send_embed(
                bot,
                title=f"📣 Event Changes – {get_name_for_tag(tag)}",
                description="\n".join(lines),
                color=get_color_for_tag(tag)
            )
            logger.info(f"Detected changes for '{tag}', snapshot updated.")
            save_current_events_for_key(key, all_events)
        else:
            logger.debug(f"No changes for '{tag}'. Snapshot unchanged.")


# ╔════════════════════════════════════════════════════════════════════╗
# ║ 📜 post_todays_happenings                                          ║
# ║ Posts all events for today and an optional greeting and image     ║
# ╚════════════════════════════════════════════════════════════════════╝
async def post_todays_happenings(bot, include_greeting: bool = False):
    today = get_today()
    all_events_for_greeting = []

    for tag in GROUPED_CALENDARS:
        await post_tagged_events(bot, tag, today)
        for meta in GROUPED_CALENDARS[tag]:
            events = await asyncio.to_thread(get_events, meta, today, today)
            all_events_for_greeting += events

    if include_greeting:
        guild = bot.guilds[0] if bot.guilds else None
        user_names = [
            m.nick or m.display_name for m in guild.members if not m.bot
        ] if guild else []

        event_titles = [e.get("summary", "a most curious happening") for e in all_events_for_greeting]
        greeting, persona = generate_greeting(event_titles, user_names)

        if greeting:
            image_path = await asyncio.to_thread(generate_image, greeting, persona)
            await send_embed(
                bot,
                title=f"The Morning Proclamation 📜 — {persona}",
                description=greeting,
                color=0xffe4b5,
                image_path=image_path
            )


# ╔════════════════════════════════════════════════════════════════════╗
# ║ 🧊 initialize_event_snapshots                                      ║
# ║ Saves a baseline snapshot of all upcoming events across calendars ║
# ╚════════════════════════════════════════════════════════════════════╝
async def initialize_event_snapshots():
    logger.info("Performing initial silent snapshot of all calendars...")
    today = get_today()
    earliest = today - timedelta(days=30)
    latest = today + timedelta(days=90)

    for tag, calendars in GROUPED_CALENDARS.items():
        all_events = []
        for meta in calendars:
            events = await asyncio.to_thread(get_events, meta, earliest, latest)
            all_events += events
        all_events.sort(key=lambda e: e["start"].get("dateTime", e["start"].get("date")))
        save_current_events_for_key(f"{tag}_full", all_events)
        logger.debug(f"Initial snapshot saved for '{tag}'")

    logger.info("Initial snapshot complete.")
