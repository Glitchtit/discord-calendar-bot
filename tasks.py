"""
tasks.py: Background scheduled tasks and their orchestration.

Includes daily/weekly posts, snapshot archiving, and AI greeting generation.
A scheduler runs once per minute, checking if any tasks should run.
"""

import asyncio
from datetime import datetime, date, timedelta
from typing import Any, Callable

from log import logger
from ai import generate_greeting_text, generate_greeting_image
from events import GROUPED_CALENDARS, get_events, save_current_events_for_key
from commands import send_embed
from environ import OPENAI_API_KEY


# ╔════════════════════════════════════════════════════════════════════╗
# 🧰 Utility: safe_call
# ╚════════════════════════════════════════════════════════════════════╝
async def safe_call(coro: Callable[..., Any], *args, **kwargs) -> None:
    """
    Executes a coroutine, catching and logging any exceptions so that
    a single task failure doesn't disrupt the entire scheduler.

    Args:
        coro: The coroutine function to call.
        *args, **kwargs: Any arguments to pass along to the coroutine.

    Returns:
        None
    """
    try:
        await coro(*args, **kwargs)
    except Exception as e:
        logger.exception(f"[tasks.py] Scheduled task {coro.__name__} encountered an error.", exc_info=e)


# ╔════════════════════════════════════════════════════════════════════╗
# 🧠 AI Greeting
# ╚════════════════════════════════════════════════════════════════════╝
async def post_ai_greeting(bot) -> None:
    """
    Generates a greeting text and image via AI, then sends them to
    the announcement channel. Skips if OPENAI_API_KEY is not available.
    """
    if not OPENAI_API_KEY:
        logger.debug("[tasks.py] AI greetings disabled due to missing OPENAI_API_KEY.")
        return

    logger.info("[tasks.py] 🤖 Generating AI greeting...")
    text = await generate_greeting_text()
    image_path = await generate_greeting_image(text)

    await send_embed(
        bot=bot,
        title="📣 Daily Greeting",
        description=text,
        image_path=image_path
    )
    logger.info("[tasks.py] ✅ AI greeting posted.")


# ╔════════════════════════════════════════════════════════════════════╗
# 📅 Daily Event Poster — Posts today's events for each tag
# ╚════════════════════════════════════════════════════════════════════╝
async def post_all_tags_today(bot) -> None:
    """
    Iterates through GROUPED_CALENDARS and posts today's events for each tag.
    """
    logger.info("[tasks.py] 🌄 Running daily tag announcements...")
    today = date.today()

    # Inline function for posting a single tag's events
    async def post_tagged_events_for_today(tag: str) -> None:
        all_events = []
        for source in GROUPED_CALENDARS.get(tag, []):
            events = await bot.loop.run_in_executor(None, get_events, source, today, today)
            all_events.extend(events)

        if not all_events:
            logger.info(f"[tasks.py] No events found for tag '{tag}' today.")
            return

        # Sort by start time
        all_events.sort(key=lambda e: e["start"].get("dateTime", e["start"].get("date")))

        desc = "\n\n".join(
            f"**{evt.get('summary', 'Untitled')}**"
            for evt in all_events
        )

        from commands import send_embed  # avoid circular import at module level
        embed_title = f"📅 Today’s Events — Tag {tag}"
        msg = f"{len(all_events)} event(s) found for {today}."

        await send_embed(
            bot=bot,
            title=embed_title,
            description=f"{msg}\n\n{desc}"
        )
        logger.info(f"[tasks.py] Posted daily events for tag '{tag}'.")

    for tag in GROUPED_CALENDARS.keys():
        await safe_call(post_tagged_events_for_today, tag)


# ╔════════════════════════════════════════════════════════════════════╗
# 📜 Weekly Summary Poster — Runs Mondays at 06:10
# ╚════════════════════════════════════════════════════════════════════╝
async def post_all_tags_week(bot) -> None:
    """
    Posts a weekly summary of events for each tag, starting from Monday to Sunday.
    Only runs on Mondays as scheduled in the scheduler.
    """
    logger.info("[tasks.py] 📚 Running weekly calendar summary...")
    now = date.today()
    monday = now - timedelta(days=now.weekday())  # get this week's Monday

    # Inline function for posting a single tag's weekly summary
    async def post_tagged_week(tag: str, start: date) -> None:
        end = start + timedelta(days=6)
        all_events = []
        for source in GROUPED_CALENDARS.get(tag, []):
            events = await bot.loop.run_in_executor(None, get_events, source, start, end)
            all_events.extend(events)

        if not all_events:
            logger.info(f"[tasks.py] No events found for tag '{tag}' this week.")
            return

        # Sort by start time
        all_events.sort(key=lambda e: e["start"].get("dateTime", e["start"].get("date")))

        from commands import send_embed
        embed_title = f"🗓️ Weekly Events — Tag {tag}"
        desc = "\n\n".join(evt.get("summary", "Untitled") for evt in all_events)
        footer = f"{len(all_events)} event(s) • {start.strftime('%d %b')} - {end.strftime('%d %b')}"

        embed_description = f"{desc}\n\n{footer}"

        await send_embed(
            bot=bot,
            title=embed_title,
            description=embed_description
        )
        logger.info(f"[tasks.py] Posted weekly events for tag '{tag}' from {start} to {end}.")

    for tag in GROUPED_CALENDARS.keys():
        await safe_call(post_tagged_week, tag, monday)


# ╔════════════════════════════════════════════════════════════════════╗
# 💾 Snapshot Archiver — Save full per-tag event data
# ╚════════════════════════════════════════════════════════════════════╝
async def archive_snapshots(bot) -> None:
    """
    Archives the full list of events for each tag for today's date.
    Useful for historical record-keeping or debugging.
    """
    logger.info("[tasks.py] 💾 Archiving full snapshots per tag...")
    today = date.today()

    def archive_for_tag(tag: str) -> None:
        events = []
        for source in GROUPED_CALENDARS.get(tag, []):
            events += get_events(source, today, today)
        save_current_events_for_key(tag + "_full", events, versioned=True)

    for tag in GROUPED_CALENDARS.keys():
        # For blocking tasks, we can run_in_executor
        await bot.loop.run_in_executor(None, archive_for_tag, tag)


# ╔════════════════════════════════════════════════════════════════════╗
# 🧠 Background Scheduler
# ╚════════════════════════════════════════════════════════════════════╝
def start_background_tasks(bot) -> None:
    """
    Main scheduler for background tasks. Runs once per minute, checking
    if the current time matches specific task times. Each call is wrapped
    in safe_call to prevent a single failure from halting the entire loop.
    """
    async def scheduler() -> None:
        try:
            while True:
                now = datetime.now()
                weekday = now.weekday()

                if now.hour == 6 and now.minute == 0:
                    await safe_call(post_ai_greeting, bot)
                    await safe_call(post_all_tags_today, bot)

                if weekday == 0 and now.hour == 6 and now.minute == 10:
                    await safe_call(post_all_tags_week, bot)

                if now.hour == 6 and now.minute == 20:
                    await safe_call(archive_snapshots, bot)

                await asyncio.sleep(60)
        except Exception as e:
            logger.exception("[tasks.py] ❌ Scheduler loop crashed!", exc_info=e)


    asyncio.create_task(scheduler())
    logger.info("[tasks.py] Background tasks initialized.")
