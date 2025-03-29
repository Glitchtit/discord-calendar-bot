from datetime import timedelta
from discord.ext import tasks
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


def start_all_tasks(bot):
    schedule_daily_posts.change_interval(minutes=1)
    watch_for_event_changes.change_interval(seconds=10)
    schedule_daily_posts.start(bot)
    watch_for_event_changes.start(bot)


@tasks.loop(minutes=1)
async def schedule_daily_posts(bot):
    now = get_today()
    time = now.strftime("%H:%M")
    dt_now = get_today()
    local_now = dt_now.today()
    if local_now.weekday() == 0 and local_now.hour == 8 and local_now.minute == 0:
        monday = get_monday_of_week(now)
        for tag in GROUPED_CALENDARS:
            await post_tagged_week(bot, tag, monday)
    if local_now.hour == 8 and local_now.minute == 1:
        await post_todays_happenings(bot, include_greeting=True)


@tasks.loop(seconds=10)
async def watch_for_event_changes(bot):
    today = get_today()
    monday = get_monday_of_week(today)

    for tag, calendars in GROUPED_CALENDARS.items():
        earliest = today - timedelta(days=30)
        latest = today + timedelta(days=90)

        all_events = []
        for meta in calendars:
            all_events += get_events(meta, earliest, latest)

        all_events.sort(key=lambda e: e["start"].get("dateTime", e["start"].get("date")))
        key = f"{tag}_full"

        prev_snapshot = load_previous_events().get(key, [])
        prev_fps = {compute_event_fingerprint(e): e for e in prev_snapshot}
        curr_fps = {compute_event_fingerprint(e): e for e in all_events}

        added = [e for fp, e in curr_fps.items() if fp not in prev_fps]
        removed = [e for fp, e in prev_fps.items() if fp not in curr_fps]

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
                f"📣 Event Changes – {get_name_for_tag(tag)}",
                "\n".join(lines),
                get_color_for_tag(tag)
            )

        save_current_events_for_key(key, all_events)


async def post_todays_happenings(bot, include_greeting: bool = False):
    today = get_today()
    all_events_for_greeting = []

    for tag in GROUPED_CALENDARS:
        await post_tagged_events(bot, tag, today)
        all_events_for_greeting += [
            e for meta in GROUPED_CALENDARS[tag]
            for e in get_events(meta, today, today)
        ]

    if include_greeting:
        guild = bot.guilds[0] if bot.guilds else None
        user_names = [
            m.nick or m.display_name for m in guild.members if not m.bot
        ] if guild else []

        event_titles = [e.get("summary", "a most curious happening") for e in all_events_for_greeting]
        greeting, persona = generate_greeting(event_titles, user_names)

        if greeting:
            image_path = generate_image(greeting, persona)
            await send_embed(bot, f"The Morning Proclamation 📜 — {persona}", greeting, color=0xffe4b5, image_path=image_path)


async def initialize_event_snapshots():
    logger.info("Performing initial silent snapshot of all calendars...")
    today = get_today()
    earliest = today - timedelta(days=30)
    latest = today + timedelta(days=90)

    for tag, calendars in GROUPED_CALENDARS.items():
        all_events = []
        for meta in calendars:
            all_events += get_events(meta, earliest, latest)
        all_events.sort(key=lambda e: e["start"].get("dateTime", e["start"].get("date")))
        save_current_events_for_key(f"{tag}_full", all_events)

    logger.info("Initial snapshot complete.")
