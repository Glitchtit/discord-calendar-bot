import asyncio
from datetime import datetime, timedelta
from log import logger

from commands import post_tagged_events, post_tagged_week
from ai import generate_greeting_text, generate_greeting_image
from environ import CALENDAR_SOURCES, ENABLE_AI_GREETINGS
from events import GROUPED_CALENDARS, save_current_events_for_key, get_events


# ╔════════════════════════════════════════════════════════════════════╗
# 🧠 Generate daily AI greeting + image
# ╚════════════════════════════════════════════════════════════════════╝
async def post_ai_greeting(bot):
    if not ENABLE_AI_GREETINGS:
        logger.debug("AI greetings disabled.")
        return

    logger.info("🤖 Generating AI greeting...")
    text = await generate_greeting_text()
    image_path = await generate_greeting_image(text)

    from commands import send_embed
    await send_embed(bot, title="📣 Daily Greeting", description=text, image_path=image_path)
    logger.info("✅ AI greeting posted.")


# ╔════════════════════════════════════════════════════════════════════╗
# 📅 Daily Event Poster — Runs every morning at 06:00
# ╚════════════════════════════════════════════════════════════════════╝
async def post_all_tags_today(bot):
    logger.info("🌄 Running daily tag announcements...")
    date = datetime.now().date()
    for tag in GROUPED_CALENDARS.keys():
        await post_tagged_events(bot, tag, date)


# ╔════════════════════════════════════════════════════════════════════╗
# 📜 Weekly Summary Poster — Runs Mondays at 06:10
# ╚════════════════════════════════════════════════════════════════════╝
async def post_all_tags_week(bot):
    logger.info("📚 Running weekly calendar summary...")
    monday = datetime.now().date()
    monday -= timedelta(days=monday.weekday())  # Ensure it's Monday
    for tag in GROUPED_CALENDARS.keys():
        await post_tagged_week(bot, tag, monday)


# ╔════════════════════════════════════════════════════════════════════╗
# 💾 Snapshot Archiver — Save full per-tag event data
# ╚════════════════════════════════════════════════════════════════════╝
async def archive_snapshots(bot):
    logger.info("💾 Archiving full snapshots per tag...")
    today = datetime.now().date()
    for tag, sources in GROUPED_CALENDARS.items():
        events = []
        for source in sources:
            events += get_events(source, today, today)
        save_current_events_for_key(tag + "_full", events, versioned=True)


# ╔════════════════════════════════════════════════════════════════════╗
# 🧠 Background Scheduler
# ╚════════════════════════════════════════════════════════════════════╝
def start_background_tasks(bot):
    async def scheduler():
        while True:
            now = datetime.now()
            target_minute = now.replace(second=0, microsecond=0)
            weekday = now.weekday()

            # 06:00 daily greeting + events
            if now.hour == 6 and now.minute == 0:
                await post_ai_greeting(bot)
                await post_all_tags_today(bot)

            # 06:10 Monday weekly summary
            elif weekday == 0 and now.hour == 6 and now.minute == 10:
                await post_all_tags_week(bot)

            # 06:20 daily snapshot archive
            elif now.hour == 6 and now.minute == 20:
                await archive_snapshots(bot)

            await asyncio.sleep(60)

    asyncio.create_task(scheduler())
