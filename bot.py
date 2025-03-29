import asyncio
import discord
from discord.ext import commands, tasks
from datetime import datetime, timedelta
from dateutil import tz
from events import (
    GROUPED_CALENDARS,
    get_events,
    get_color_for_tag,
    get_name_for_tag
)
from ai import generate_greeting, generate_image
from environ import DISCORD_BOT_TOKEN, ANNOUNCEMENT_CHANNEL_ID
from log import logger
import os

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="/", intents=intents)
last_greeting_date = None


def format_event(event) -> str:
    start = event["start"].get("dateTime", event["start"].get("date"))
    end = event["end"].get("dateTime", event["end"].get("date"))
    title = event.get("summary", "No Title")
    location = event.get("location", "")
    if "T" in start:
        start_dt = datetime.fromisoformat(start.replace("Z", "+00:00")).astimezone(tz.tzlocal())
        start_str = start_dt.strftime("%Y-%m-%d %H:%M")
    else:
        start_str = start
    if "T" in end:
        end_dt = datetime.fromisoformat(end.replace("Z", "+00:00")).astimezone(tz.tzlocal())
        end_str = end_dt.strftime("%Y-%m-%d %H:%M")
    else:
        end_str = end
    return f"- {title} ({start_str} to {end_str}" + (f", at {location})" if location else ")")


async def send_embed(title: str, description: str, color: int = 5814783, image_path: str | None = None):
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


async def post_todays_happenings(include_greeting: bool = False):
    global last_greeting_date
    logger.info("Posting today's happenings.")
    today = datetime.now(tz=tz.tzlocal()).date()
    weekday_name = today.strftime("%A")
    all_events_for_greeting = []
    for tag, calendars in GROUPED_CALENDARS.items():
        all_events = []
        for meta in calendars:
            logger.debug(f"[{tag}] Getting today's events from: {meta['name']}")
            all_events += get_events(meta, today, today)
        if all_events:
            all_events.sort(key=lambda e: e["start"].get("dateTime", e["start"].get("date")))
            lines = [format_event(e) for e in all_events]
            await send_embed(
                f"Today’s Happenings – {weekday_name} for {get_name_for_tag(tag)}",
                "\n".join(lines),
                get_color_for_tag(tag)
            )
            all_events_for_greeting += all_events

    if include_greeting or last_greeting_date != today:
        event_titles = [e.get("summary", "a most curious happening") for e in all_events_for_greeting]
        greeting, persona = generate_greeting(event_titles)
        if greeting:
            image_path = generate_image(greeting, persona)
            await send_embed(
                f"The Morning Proclamation 📜 — {persona}",
                greeting,
                color=0xffe4b5,
                image_path=image_path
            )
            last_greeting_date = today


async def post_weeks_happenings():
    logger.info("Posting this week's happenings.")
    now = datetime.now(tz=tz.tzlocal()).date()
    monday = now - timedelta(days=now.weekday())
    end = monday + timedelta(days=6)
    for tag, calendars in GROUPED_CALENDARS.items():
        all_events = []
        for meta in calendars:
            logger.debug(f"[{tag}] Getting weekly events from: {meta['name']}")
            all_events += get_events(meta, monday, end)
        if not all_events:
            logger.debug(f"[{tag}] No weekly events found.")
            continue
        events_by_day = {}
        for e in all_events:
            start_str = e["start"].get("dateTime", e["start"].get("date"))
            dt = datetime.fromisoformat(start_str.replace("Z", "+00:00")) if "T" in start_str else datetime.fromisoformat(start_str)
            day = dt.date()
            events_by_day.setdefault(day, []).append(e)
        lines = []
        for i in range(7):
            day = monday + timedelta(days=i)
            if day in events_by_day:
                lines.append(f"**{day.strftime('%A')}**")
                day_events = sorted(events_by_day[day], key=lambda e: e["start"].get("dateTime", e["start"].get("date")))
                lines.extend(format_event(e) for e in day_events)
                lines.append("")
        await send_embed(
            f"This Week’s Happenings for {get_name_for_tag(tag)}",
            "\n".join(lines),
            get_color_for_tag(tag)
        )


@bot.event
async def on_ready():
    logger.info(f"Logged in as {bot.user}")
    await post_todays_happenings(include_greeting=True)
    await post_weeks_happenings()
    schedule_daily_posts.start()


@tasks.loop(minutes=1)
async def schedule_daily_posts():
    now = datetime.now(tz=tz.tzlocal())
    if now.hour == 8 and now.minute == 1:
        await post_todays_happenings(include_greeting=True)
    if now.weekday() == 0 and now.hour == 8 and now.minute == 0:
        await post_weeks_happenings()


@bot.slash_command(name="today", description="Post today's events")
async def today_command(ctx):
    logger.info(f"/{ctx.command.name} used by {ctx.author} in {ctx.channel}")
    await ctx.defer()
    await post_todays_happenings(include_greeting=False)
    await ctx.respond("Posted today's events.")


@bot.slash_command(name="week", description="Post this week's events")
async def week_command(ctx):
    logger.info(f"/{ctx.command.name} used by {ctx.author} in {ctx.channel}")
    await ctx.defer()
    await post_weeks_happenings()
    await ctx.respond("Posted this week's events.")


@bot.slash_command(name="greet", description="Post the morning greeting with image")
async def greet_command(ctx):
    logger.info(f"/{ctx.command.name} used by {ctx.author} in {ctx.channel}")
    await ctx.defer()
    await post_todays_happenings(include_greeting=True)
    await ctx.respond("Greeting and image posted.")


if __name__ == "__main__":
    if not DISCORD_BOT_TOKEN:
        raise ValueError("DISCORD_BOT_TOKEN is not set in environment.")
    bot.run(DISCORD_BOT_TOKEN)
