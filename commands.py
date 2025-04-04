import os
import discord
from discord import app_commands
import dateparser

from events import GROUPED_CALENDARS, get_events, get_name_for_tag, get_color_for_tag
from utils import format_event, get_today
from log import logger
from ai import generate_greeting_text, generate_greeting_image


# ╔════════════════════════════════════════════════════════════════════╗
# 📣 AI Greeting Command — AI-generated greeting + image
# ╚════════════════════════════════════════════════════════════════════╝
@app_commands.command(name="greet", description="Post an AI-generated greeting with today's schedule")
async def greet(interaction: discord.Interaction):
    await interaction.response.defer()
    logger.info(f"🎨 Generating AI greeting for {interaction.user}...")

    # Generate greeting text
    greeting_text = await generate_greeting_text()
    
    # Generate AI image for the greeting
    image_path = await generate_greeting_image(greeting_text)

    # Send embed with greeting
    await send_embed(interaction.bot, title="📣 Daily AI Greeting", description=greeting_text, image_path=image_path)
    logger.info(f"✅ AI greeting posted.")


# ╔════════════════════════════════════════════════════════════════════╗
# 📅 /herald [tag] — Posts today's events for a calendar tag
# ╚════════════════════════════════════════════════════════════════════╝
@app_commands.command(name="herald", description="Post today's events for a calendar tag")
@app_commands.describe(tag="Tag name (e.g., A, B, T)")
@app_commands.autocomplete(tag=lambda i, c: [
    app_commands.Choice(name=tag, value=tag) for tag in sorted(GROUPED_CALENDARS)
    if tag.startswith(c.value.upper()) or c.value == ""
])
async def herald(interaction: discord.Interaction, tag: str):
    await interaction.response.defer()
    logger.info(f"📣 /herald called by {interaction.user} for tag '{tag}'")

    today = get_today()
    all_events = []
    for source in GROUPED_CALENDARS.get(tag.upper(), []):
        events = await interaction.bot.loop.run_in_executor(None, get_events, source, today, today)
        all_events.extend(events)

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
    await interaction.followup.send(embed=embed)


# ╔════════════════════════════════════════════════════════════════════╗
# 📅 /agenda [date] — Returns events for any given day (natural language)
# ╚════════════════════════════════════════════════════════════════════╝
@app_commands.command(name="agenda", description="See events for a specific date (natural language supported)")
@app_commands.describe(date="Examples: today, tomorrow, next Thursday")
async def agenda(interaction: discord.Interaction, date: str):
    await interaction.response.defer()
    logger.info(f"📅 /agenda called by {interaction.user}: {date!r}")

    dt = dateparser.parse(date)
    if not dt:
        await interaction.followup.send("⚠️ Could not understand that date.")
        return

    day = dt.date()
    all_events = []
    for tag, sources in GROUPED_CALENDARS.items():
        for source in sources:
            events = await interaction.bot.loop.run_in_executor(None, get_events, source, day, day)
            all_events.extend(events)

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
    await interaction.followup.send(embed=embed)


# ╔════════════════════════════════════════════════════════════════════╗
# 📤 send_embed Helper Function — Sends embeds to the announcement channel
# ╚════════════════════════════════════════════════════════════════════╝
async def send_embed(bot, embed: discord.Embed = None, title: str = "", description: str = "", color: int = 5814783, image_path: str | None = None):
    if isinstance(embed, str):
        logger.warning("send_embed() received a string instead of an Embed. Converting values assuming misuse.")
        description = embed
        embed = None
    from environ import ANNOUNCEMENT_CHANNEL_ID
    if not ANNOUNCEMENT_CHANNEL_ID:
        logger.warning("ANNOUNCEMENT_CHANNEL_ID not set.")
        return
    channel = bot.get_channel(ANNOUNCEMENT_CHANNEL_ID)
    if not channel:
        logger.error("Channel not found. Check ANNOUNCEMENT_CHANNEL_ID.")
        return

    if embed is None:
        embed = discord.Embed(title=title, description=description, color=color)

    if image_path and os.path.exists(image_path):
        file = discord.File(image_path, filename="image.png")
        embed.set_image(url="attachment://image.png")
        await channel.send(embed=embed, file=file)
    else:
        await channel.send(embed=embed)


# ╔════════════════════════════════════════════════════════════════════╗
# 🔍 Autocomplete Helper — Resolves slash command inputs for tags
# ╚════════════════════════════════════════════════════════════════════╝
def get_known_tags():
    return list(GROUPED_CALENDARS.keys())


async def autocomplete_tag(interaction: discord.Interaction, current: str):
    return [
        app_commands.Choice(name=tag, value=tag)
        for tag in get_known_tags() if current.lower() in tag.lower()
    ]
