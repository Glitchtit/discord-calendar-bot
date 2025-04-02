import discord
from discord.ext import commands
from discord import app_commands
from datetime import datetime
import dateparser

from log import logger
from events import (
    load_calendar_sources,
    GROUPED_CALENDARS,
    USER_TAG_MAP,
    TAG_NAMES,
    TAG_COLORS,
    get_events
)
from ai import generate_greeting, generate_image
from commands import (
    post_tagged_events,
    post_tagged_week,
    send_embed,
    autocomplete_tag,
    autocomplete_range,
    autocomplete_agenda_target,
    autocomplete_agenda_input
)
from tasks import initialize_event_snapshots, start_all_tasks, post_todays_happenings
from utils import get_today, get_monday_of_week, resolve_input_to_tags

# ╔═════════════════════════════════════════════════════════════╗
# ║ 🤖 Discord Bot Initialization                               ║
# ║ Configures the bot with necessary intents and slash system ║
# ╚═════════════════════════════════════════════════════════════╝
intents = discord.Intents.default()
intents.members = True
bot = commands.Bot(command_prefix="/", intents=intents)


# ╔═════════════════════════════════════════════════════════════╗
# ║ 🟢 on_ready                                                  ║
# ║ Called once the bot is online and ready                     ║
# ╚═════════════════════════════════════════════════════════════╝
@bot.event
async def on_ready():
    logger.info(f"Logged in as {bot.user}")
    try:
        await resolve_tag_mappings()
        synced = await bot.tree.sync()
        logger.info(f"Synced {len(synced)} commands.")
    except Exception:
        logger.exception("Failed during on_ready or slash sync.")

    await initialize_event_snapshots()
    start_all_tasks(bot)


# ╔═════════════════════════════════════════════════════════════╗
# ║ 📜 /herald                                                   ║
# ║ Posts the weekly + daily event summaries for all tags       ║
# ╚═════════════════════════════════════════════════════════════╝
@bot.tree.command(
    name="herald",
    description="Post all weekly and daily events for every calendar tag"
)
async def herald_command(interaction: discord.Interaction):
    await interaction.response.defer()
    today = get_today()
    monday = get_monday_of_week(today)

    for tag in GROUPED_CALENDARS:
        await post_tagged_week(bot, tag, monday)
    for tag in GROUPED_CALENDARS:
        await post_tagged_events(bot, tag, today)

    await interaction.followup.send("Herald posted for **all** tags — week and today.")


# ... (imports and setup remain unchanged)

# ╔═════════════════════════════════════════════════════════════╗
# ║ 🗓️ /agenda                                                   ║
# ║ Posts events for a given date or natural language input     ║
# ╚═════════════════════════════════════════════════════════════╝
@bot.tree.command(
    name="agenda",
    description="Post events for a date or range (e.g. 'tomorrow', 'week'), with optional tag filter"
)
@app_commands.describe(
    input="A natural date or keyword: 'today', 'week', 'next monday', 'April 10', 'DD.MM'",
    target="Optional calendar tag or display name (e.g. Bob, xXsNiPeRkId69Xx)"
)
@app_commands.autocomplete(input=autocomplete_agenda_input, target=autocomplete_agenda_target)
async def agenda_command(interaction: discord.Interaction, input: str, target: str = ""):
    await interaction.response.defer()

    today = get_today()
    tags = resolve_input_to_tags(target, TAG_NAMES, GROUPED_CALENDARS) if target.strip() else list(GROUPED_CALENDARS.keys())

    if not tags:
        await interaction.followup.send("No matching tags or names found.")
        return

    any_posted = False
    if input.lower() == "today":
        for tag in tags:
            posted = await post_tagged_events(bot, tag, today)
            any_posted |= posted
        label = today.strftime("%A, %B %d")
    elif input.lower() == "week":
        monday = get_monday_of_week(today)
        for tag in tags:
            await post_tagged_week(bot, tag, monday)
        any_posted = True  # Weekly always posts if calendars are valid
        label = f"week of {monday.strftime('%B %d')}"
    else:
        parsed = dateparser.parse(input)
        if not parsed:
            await interaction.followup.send("Could not understand the date. Try 'today', 'week', or a real date.")
            return
        day = parsed.date()
        for tag in tags:
            posted = await post_tagged_events(bot, tag, day)
            any_posted |= posted
        label = day.strftime("%A, %B %d")

    tag_names = ", ".join(TAG_NAMES.get(t, t) for t in tags)
    if any_posted:
        await interaction.followup.send(f"Agenda posted for **{tag_names}** on **{label}**.")
    else:
        await interaction.followup.send(f"No events found for **{tag_names}** on **{label}**.")



# ╔═════════════════════════════════════════════════════════════╗
# ║ 🎭 /greet                                                    ║
# ║ Generates a persona-based medieval greeting with image      ║
# ╚═════════════════════════════════════════════════════════════╝
@bot.tree.command(name="greet", description="Post the morning greeting with image")
async def greet_command(interaction: discord.Interaction):
    await interaction.response.defer()
    await post_todays_happenings(bot, include_greeting=True)
    await interaction.followup.send("Greeting and image posted.")


# ╔═════════════════════════════════════════════════════════════╗
# ║ 🔄 /reload                                                   ║
# ║ Reloads calendar sources and tag-to-user mapping            ║
# ╚═════════════════════════════════════════════════════════════╝
@bot.tree.command(name="reload", description="Reload calendar sources and tag-user mappings")
async def reload_command(interaction: discord.Interaction):
    await interaction.response.defer()
    load_calendar_sources()
    await resolve_tag_mappings()
    await interaction.followup.send("Reloaded calendar sources and tag mappings.")


# ╔═════════════════════════════════════════════════════════════╗
# ║ 📇 /who                                                      ║
# ║ Displays all active tags and their mapped display names     ║
# ╚═════════════════════════════════════════════════════════════╝
@bot.tree.command(name="who", description="List calendar tags and their assigned users")
async def who_command(interaction: discord.Interaction):
    await interaction.response.defer()
    lines = [f"**{tag}** → {TAG_NAMES.get(tag, tag)}" for tag in sorted(GROUPED_CALENDARS)]
    await interaction.followup.send("**Calendar Tags:**\n" + "\n".join(lines))


# ╔═════════════════════════════════════════════════════════════╗
# ║ 🔗 resolve_tag_mappings                                      ║
# ║ Assigns display names and colors to tags based on members   ║
# ╚═════════════════════════════════════════════════════════════╝
async def resolve_tag_mappings():
    logger.info("Resolving Discord tag-to-name mappings...")
    guild = discord.utils.get(bot.guilds)
    if not guild:
        logger.warning("No guild found.")
        return
    for user_id, tag in USER_TAG_MAP.items():
        member = guild.get_member(user_id)
        if member:
            TAG_NAMES[tag] = member.nick or member.display_name
            role_color = next((r.color.value for r in member.roles if r.color.value != 0), 0x95a5a6)
            TAG_COLORS[tag] = role_color
            logger.info(f"Assigned {tag}: name={TAG_NAMES[tag]}, color=#{role_color:06X}")
        else:
            logger.warning(f"Could not resolve Discord member for ID {user_id}")
