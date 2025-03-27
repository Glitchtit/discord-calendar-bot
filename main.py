import os
import time
import asyncio
import schedule
import threading
import discord
from discord.ext import commands
from discord import app_commands

from datetime import datetime
from dateutil import tz
from dateutil.relativedelta import relativedelta, SU

# -- Local module imports --
from calendar_tasks import (
    get_all_calendar_events,
    detect_changes,
    load_previous_events,
    save_current_events_for_key,
    format_event,
    ALL_EVENTS_KEY
)
from ai import store, generate_greeting, generate_image_prompt, generate_image
import openai

TOKEN = os.environ.get("DISCORD_BOT_TOKEN", "")
ANNOUNCEMENT_CHANNEL_ID = os.environ.get("ANNOUNCEMENT_CHANNEL_ID", "")

bot = commands.Bot(command_prefix="!", intents=discord.Intents.default())

@bot.event
async def on_ready():
    print(f"Bot connected as {bot.user} (ID: {bot.user.id})")
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} slash commands.")
    except Exception as e:
        print(f"Error syncing slash commands: {e}")
    start_scheduling_thread()

# -------------------------------------------------
# SCHEDULING
# -------------------------------------------------
def run_schedule_loop():
    while True:
        schedule.run_pending()
        time.sleep(30)

def start_scheduling_thread():
    schedule.every().day.at("08:00").do(task_daily_update_and_check)
    t = threading.Thread(target=run_schedule_loop, daemon=True)
    t.start()

def task_daily_update_and_check():
    channel = bot.get_channel(int(ANNOUNCEMENT_CHANNEL_ID)) if ANNOUNCEMENT_CHANNEL_ID else None
    new_events = get_all_calendar_events()
    prev_data = load_previous_events()
    old_events = prev_data.get(ALL_EVENTS_KEY, [])

    changes = detect_changes(old_events, new_events)
    if changes:
        save_current_events_for_key(ALL_EVENTS_KEY, new_events)
        if channel:
            async def post_changes():
                chunk_size = 1800
                current_block = []
                current_len = 0
                for c in changes:
                    if current_len + len(c) + 1 > chunk_size:
                        await channel.send("**Calendar Changes Detected**\n" + "\n".join(current_block))
                        current_block = []
                        current_len = 0
                    current_block.append(c)
                    current_len += len(c) + 1
                if current_block:
                    await channel.send("**Calendar Changes Detected**\n" + "\n".join(current_block))
            asyncio.run_coroutine_threadsafe(post_changes(), bot.loop)
    else:
        if not old_events:
            save_current_events_for_key(ALL_EVENTS_KEY, new_events)

    update_store_embeddings(old_events, new_events)

    if channel:
        async def post_daily_greeting():
            event_titles = [evt.get("summary", "mysterious event") for evt in new_events]
            greeting_text = generate_greeting(event_titles)
            await channel.send(greeting_text)
            prompt = generate_image_prompt(event_titles)
            try:
                img_path = generate_image(prompt)
                await channel.send(file=discord.File(img_path))
            except Exception as e:
                await channel.send(f"[Error generating image] {e}")
        asyncio.run_coroutine_threadsafe(post_daily_greeting(), bot.loop)

def update_store_embeddings(old_events, new_events):
    old_ids = {e["id"] for e in old_events}
    new_ids = {e["id"] for e in new_events}

    for removed_id in (old_ids - new_ids):
        store.remove_event(removed_id)

    for evt in new_events:
        eid = evt["id"]
        summary = evt.get("summary", "")
        start = evt["start"].get("dateTime") or evt["start"].get("date", "")
        end = evt["end"].get("dateTime") or evt["end"].get("date", "")
        loc = evt.get("location", "")
        desc = evt.get("description", "")
        text_repr = (
            f"Title: {summary}\n"
            f"Start: {start}\n"
            f"End: {end}\n"
            f"Location: {loc}\n"
            f"Desc: {desc}"
        )
        store.add_or_update_event(eid, text_repr)

# -------------------------------------------------
# SLASH COMMANDS
# -------------------------------------------------
@bot.tree.command(name="ask", description="Ask the AI anything about your calendar or otherwise.")
@app_commands.describe(query="Your question or query.")
async def ask_command(interaction: discord.Interaction, query: str):
    await interaction.response.defer()
    message = await interaction.followup.send("🔮 Summoning an answer...")

    try:
        top_events = store.query(query, top_k=5)
        if not top_events:
            system_msg = "You are a helpful assistant. You have no calendar context available yet."
        else:
            relevant_text = "\n\n".join(top_events)
            system_msg = (
                "You are a helpful scheduling assistant with knowledge of the following relevant events:\n\n"
                f"{relevant_text}\n\n"
                "Use them to answer the user's query accurately. "
                "If the query does not relate to these events, answer to the best of your ability."
            )

        response = openai.ChatCompletion.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": query},
            ],
            stream=True
        )

        full_reply = ""
        buffer = ""
        last_edit = time.time()

        async def maybe_edit():
            nonlocal buffer, full_reply, last_edit
            now = time.time()
            if buffer and now - last_edit > 0.5:
                full_reply += buffer
                await message.edit(content=full_reply)
                buffer = ""
                last_edit = now

        for chunk in response:
            delta = chunk["choices"][0]["delta"].get("content", "")
            buffer += delta
            await maybe_edit()

        full_reply += buffer
        await message.edit(content=full_reply or "🤷 No response.")

    except Exception as e:
        await message.edit(content=f"[Error streaming response] {e}")

@bot.tree.command(name="uwu", description="Generate a cringe catgirl greeting for this week's events.")
async def uwu_command(interaction: discord.Interaction):
    await interaction.response.defer()

    prev_data = load_previous_events()
    all_events = prev_data.get(ALL_EVENTS_KEY, [])

    now_local = datetime.now(tz.tzlocal())
    end_of_week = now_local + relativedelta(weekday=SU, hour=23, minute=59, second=59)

    this_week_events = []
    for e in all_events:
        start_str = e["start"].get("dateTime") or e["start"].get("date")
        if "T" in start_str:
            start_dt = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
        else:
            start_dt = datetime.fromisoformat(start_str).replace(hour=0, minute=0, second=0, tzinfo=tz.tzutc())

        if start_dt.tzinfo is None:
            start_dt = start_dt.replace(tzinfo=tz.tzutc())
        start_dt_local = start_dt.astimezone(tz.tzlocal())

        if now_local <= start_dt_local <= end_of_week:
            this_week_events.append(e)

    event_titles = [evt.get("summary", "mysterious event") for evt in this_week_events]

    greeting_text = generate_greeting(event_titles)
    await interaction.followup.send(f"**UwU Greeting**\n{greeting_text}")

    prompt = generate_image_prompt(event_titles)
    try:
        img_path = generate_image(prompt)
        await interaction.followup.send(file=discord.File(img_path))
    except Exception as e:
        await interaction.followup.send(f"[Error generating image] {e}")

# -------------------------------------------------
# MAIN
# -------------------------------------------------
if __name__ == "__main__":
    if not TOKEN:
        print("Error: DISCORD_BOT_TOKEN environment variable not set.")
        exit(1)

    bot.run(TOKEN)
