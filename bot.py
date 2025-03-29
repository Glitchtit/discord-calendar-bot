import asyncio
import discord
from discord.ext import commands, tasks
from discord import app_commands
from datetime import datetime, timedelta
from dateutil import tz
from events import GROUPED_CALENDARS, get_events, get_color_for_tag, get_name_for_tag
from ai import generate_greeting, generate_image
from environ import DISCORD_BOT_TOKEN, ANNOUNCEMENT_CHANNEL_ID
from log import logger
import os
import dateparser

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


def get_known_tags():
    return list(GROUPED_CALENDARS.keys())


async def post_tagged_events(tag: str, day: datetime.date):
    calendars = GROUPED_CALENDARS.get(tag)
    if not calendars:
        logger.warning(f"No calendars found for tag: {tag}")
        return
    all_events = []
    for meta in calendars:
        all_events += get_events(meta, day, day)
    if all_events:
        all_events.sort(key=lambda e: e["start"].get("dateTime", e["start"].get("date")))
        lines = [format_event(e) for e in all_events]
        await send_embed(
            f"Herald’s Scroll – {get_name_for_tag(tag)} on {day.strftime('%A')}",
            "\n".join(lines),
            get_color_for_tag(tag)
        )
    else:
        await send_embed(
            f"Herald’s Scroll – {get_name_for_tag(tag)}",
            "No events on this day.",
            get_color_for_tag(tag)
        )


async def post_tagged_week(tag: str, monday: datetime.date):
    calendars = GROUPED_CALENDARS.get(tag)
    if not calendars:
        logger.warning(f"No calendars for tag {tag}")
        return
    end = monday + timedelta(days=6)
    all_events = []
    for meta in calendars:
        all_events += get_events(meta, monday, end)
    if not all_events:
        await send_embed(f"Herald’s Week for {get_name_for_tag(tag)}", "No events this week.", get_color_for_tag(tag))
        return
    events_by_day = {}
    for e in all_events:
        start_str = e["start"].get("dateTime", e["start"].get("date"))
        dt = datetime.fromisoformat(start_str.replace("Z", "+00:00")) if "T" in start_str else datetime.fromisoformat(start_str)
        events_by_day.setdefault(dt.date(), []).append(e)
    lines = []
    for i in range(7):
        day = monday + timedelta(days=i)
        if day in events_by_day:
            lines.append(f"**{day.strftime('%A')}**")
            day_events = sorted(events_by_day[day], key=lambda e: e["start"].get("dateTime", e["start"].get("date")))
            lines.extend(format_event(e) for e in day_events)
            lines.append("")
    await send_embed(f"Herald’s Week – {get_name_for_tag(tag)}", "\n".join(lines), get_color_for_tag(tag))


async def post_todays_happenings(include_greeting: bool = False):
    global last_greeting_date
    today = datetime.now(tz=tz.tzlocal()).date()
    weekday_name = today.strftime("%A")
    all_events_for_greeting = []

    for tag, calendars in GROUPED_CALENDARS.items():
        all_events = []
        for meta in calendars:
            all_events += get_events(meta, today, today)
        if all_events:
            all_events.sort(key=lambda e: e["start"].get("dateTime", e["start"].get("date")))
            lines = [format_event(e) for e in all_events]
            await send_embed(f"Today’s Happenings – {weekday_name} for {get_name_for_tag(tag)}", "\n".join(lines), get_color_for_tag(tag))
            all_events_for_greeting += all_events

    if include_greeting or last_greeting_date != today:
        event_titles = [e.get("summary", "a most curious happening") for e in all_events_for_greeting]
        greeting, persona = generate_greeting(event_titles)
        if greeting:
            image_path = generate_image(greeting, persona)
            await send_embed(f"The Morning Proclamation 📜 — {persona}", greeting, color=0xffe4b5, image_path=image_path)
            last_greeting_date = today


async def post_weeks_happenings():
    now = datetime.now(tz=tz.tzlocal()).date()
    monday = now - timedelta(days=now.weekday())
    end = monday + timedelta(days=6)
    for tag in GROUPED_CALENDARS:
        await post_tagged_week(tag, monday)


async def post_next_weeks_happenings():
    next_monday = datetime.now(tz=tz.tzlocal()).date() + timedelta(days=7 - datetime.now(tz=tz.tzlocal()).weekday())
    for tag in GROUPED_CALENDARS:
        await post_tagged_week(tag, next_monday)


@bot.event
async def on_ready():
    logger.info(f"Logged in as {bot.user}")
    try:
        synced = await bot.tree.sync()
        logger.info(f"Synced {len(synced)} commands.")
    except Exception:
        logger.exception("Failed to sync slash commands.")
    await post_weeks_happenings()
    await post_todays_happenings(include_greeting=True)
    schedule_daily_posts.start()


@tasks.loop(minutes=1)
async def schedule_daily_posts():
    now = datetime.now(tz=tz.tzlocal())
    if now.weekday() == 0 and now.hour == 8 and now.minute == 0:
        await post_weeks_happenings()
    if now.hour == 8 and now.minute == 1:
        await post_todays_happenings(include_greeting=True)


@bot.tree.command(name="today", description="Post today's events")
async def today_command(interaction: discord.Interaction):
    await interaction.response.defer()
    await post_todays_happenings(include_greeting=False)
    await interaction.followup.send("Posted today's events.")


@bot.tree.command(name="week", description="Post this week's events")
async def week_command(interaction: discord.Interaction):
    await interaction.response.defer()
    await post_weeks_happenings()
    await interaction.followup.send("Posted this week's events.")


@bot.tree.command(name="next", description="Post next week's events")
async def next_command(interaction: discord.Interaction):
    await interaction.response.defer()
    await post_next_weeks_happenings()
    await interaction.followup.send("Posted next week's events.")


@bot.tree.command(name="greet", description="Post the morning greeting with image")
async def greet_command(interaction: discord.Interaction):
    await interaction.response.defer()
    await post_todays_happenings(include_greeting=True)
    await interaction.followup.send("Greeting and image posted.")


@bot.tree.command(name="agenda", description="Show events for a specific date")
@app_commands.describe(date="A natural language date (e.g. 'tomorrow', 'March 28')")
async def agenda_command(interaction: discord.Interaction, date: str):
    await interaction.response.defer()
    parsed = dateparser.parse(date)
    if not parsed:
        await interaction.followup.send("Could not understand the date. Try 'tomorrow', 'next monday', or '2025-03-28'.")
        return
    day = parsed.date()
    for tag in GROUPED_CALENDARS:
        await post_tagged_events(tag, day)
    await interaction.followup.send(f"Agenda posted for {day.strftime('%A, %B %d')}.")


@bot.tree.command(name="herald", description="Post daily or weekly events for a tag")
@app_commands.describe(tag="Calendar tag", range="today or week")
@app_commands.autocomplete(
    tag=lambda _: [app_commands.Choice(name=t, value=t) for t in get_known_tags()],
    range=lambda _: [app_commands.Choice(name=r, value=r) for r in ["today", "week"]]
)
async def herald_command(interaction: discord.Interaction, tag: str, range: str = "today"):
    await interaction.response.defer()
    if range == "week":
        monday = datetime.now(tz=tz.tzlocal()).date() - timedelta(days=datetime.now(tz=tz.tzlocal()).weekday())
        await post_tagged_week(tag, monday)
    else:
        await post_tagged_events(tag, datetime.now(tz=tz.tzlocal()).date())
    await interaction.followup.send(f"Herald posted for {tag} ({range}).")


@bot.tree.command(name="reload", description="Reload calendar configuration")
async def reload_command(interaction: discord.Interaction):
    from events import load_calendar_sources
    await interaction.response.defer()
    load_calendar_sources()
    await interaction.followup.send("Calendar sources reloaded.")


if __name__ == "__main__":
    if not DISCORD_BOT_TOKEN:
        raise ValueError("DISCORD_BOT_TOKEN is not set in environment.")
    bot.run(DISCORD_BOT_TOKEN)
