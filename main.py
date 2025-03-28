import os
import time
import asyncio
import schedule
import threading
import discord
from discord.ext import commands
from discord import app_commands
from datetime import datetime
from collections import defaultdict
from dateutil import tz
from datetime import timedelta
from dateutil.relativedelta import relativedelta, SU
import openai
from calendar_tasks import (
    get_all_calendar_events,
    detect_changes,
    load_previous_events,
    save_current_events_for_key,
    format_event,
    get_today_event_titles,
    ALL_EVENTS_KEY
)
from ai import store, generate_greeting, generate_image_prompt, generate_image
from date_utils import extract_date_range_from_query, is_calendar_prompt
from embeddings import EventEmbeddingStore
from log import log

TOKEN = os.environ.get("DISCORD_BOT_TOKEN", "")
ANNOUNCEMENT_CHANNEL_ID = os.environ.get("ANNOUNCEMENT_CHANNEL_ID", "")

bot = commands.Bot(command_prefix="!", intents=discord.Intents.default())

@bot.event
async def on_ready():
    log.info(f"Bot connected as {bot.user} (ID: {bot.user.id})")
    try:
        synced = await bot.tree.sync()
        log.info(f"Synced {len(synced)} slash commands.")
    except Exception as e:
        log.warning(f"Error syncing slash commands: {e}")

    asyncio.create_task(run_initial_sync())
    start_scheduling_thread()

async def run_initial_sync():
    log.info("[Startup] Performing initial calendar sync and embedding...")
    await task_daily_update_and_check()

def run_schedule_loop():
    while True:
        schedule.run_pending()
        time.sleep(30)

def start_scheduling_thread():
    schedule.every().day.at("08:00").do(lambda: asyncio.run(task_daily_update_and_check()))
    t = threading.Thread(target=run_schedule_loop, daemon=True)
    t.start()

async def task_daily_update_and_check():
    log.info("[Sync] Starting daily update...")
    channel = bot.get_channel(int(ANNOUNCEMENT_CHANNEL_ID)) if ANNOUNCEMENT_CHANNEL_ID else None
    new_events = get_all_calendar_events()
    log.info(f"[Sync] Fetched {len(new_events)} upcoming events.")

    prev_data = load_previous_events()
    old_events = prev_data.get(ALL_EVENTS_KEY, [])
    changes = detect_changes(old_events, new_events)

    if changes:
        log.info(f"[Sync] Detected {len(changes)} calendar changes.")
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
            asyncio.create_task(post_changes())
    else:
        log.info("[Sync] No calendar changes found.")
        if not old_events:
            log.info("[Sync] No previous event snapshot — saving current events.")
            save_current_events_for_key(ALL_EVENTS_KEY, new_events)

    before_count = len(store.get_all_event_ids())
    await update_store_embeddings(old_events, new_events)
    after_count = len(store.get_all_event_ids())
    log.info(f"[Sync] Embedding store now contains {after_count} events (was {before_count}, net change: {after_count - before_count}).")

    if channel:
        async def post_daily_greeting():
            event_titles = get_today_event_titles(new_events)
            greeting_text = generate_greeting(event_titles)
            await channel.send(greeting_text)
           # prompt = generate_image_prompt(event_titles)
            #try:
             #   img_path = await asyncio.to_thread(generate_image, prompt)
              #  await channel.send(file=discord.File(img_path))
            #except Exception as e:
             #   await channel.send(f"[Error generating image] {e}")
        asyncio.create_task(post_daily_greeting())

async def update_store_embeddings(old_events, new_events):
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
        text_repr = f"Title: {summary}\nStart: {start}\nEnd: {end}\nLocation: {loc}\nDesc: {desc}"
        await asyncio.to_thread(store.add_or_update_event, eid, text_repr)

@bot.tree.command(name="what", description="Ask the AI anything about your calendar or otherwise.")
@app_commands.describe(query="Your question or query.")
async def ask_command(interaction: discord.Interaction, query: str):
    await interaction.response.defer()
    message = await interaction.followup.send("🔮 Summoning an answer...")

    try:
        from dateutil import tz

        # Load all events and keep those within the next 30 days
        all_events = load_previous_events().get(ALL_EVENTS_KEY, [])
        now = datetime.now(tz=tz.tzlocal())
        future_cutoff = now + timedelta(days=30)

        def is_upcoming(event):
            start_str = event["start"].get("dateTime") or event["start"].get("date")
            dt = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
            dt_local = dt.astimezone(tz.tzlocal())
            return now <= dt_local <= future_cutoff

        relevant_events = [e for e in all_events if is_upcoming(e)]

        # Optionally filter by tag in query
        query_lower = query.lower()
        if "thomas" in query_lower:
            relevant_events = [e for e in relevant_events if e.get("tag", "").upper() in {"T", "B"}]
        elif "anniina" in query_lower:
            relevant_events = [e for e in relevant_events if e.get("tag", "").upper() in {"A", "B"}]

        # Format events as blocks of text
        event_blocks = []
        for e in relevant_events:
            title = e.get("summary", "")
            start = e["start"].get("dateTime") or e["start"].get("date", "")
            end = e["end"].get("dateTime") or e["end"].get("date", "")
            loc = e.get("location", "")
            desc = e.get("description", "")
            block = f"Title: {title}\nStart: {start}\nEnd: {end}\nLocation: {loc}\nDesc: {desc}"
            event_blocks.append(block)

        if not event_blocks:
            await message.edit(content="🤷 No upcoming events found.")
            return

        # Construct prompt for GPT
        system_msg = (
            "You are a helpful scheduling assistant. Below is a list of upcoming events:\n\n"
            + "\n\n".join(event_blocks) +
            "\n\nBased on the user's question, list or describe the relevant events. "
            "If the question includes a time range like 'next week' or 'this Friday', figure out which events apply and explain them clearly."
            "If nothing else is specified, categorize the events per day of the week"
        )

        response = openai.ChatCompletion.create(
            model="gpt-4o",
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
        log.exception("[ASK Command] Error while generating response")
        await message.edit(content=f"[Error streaming response] {e}")



@bot.tree.command(name="uwu", description="Generate a cringe catgirl greeting for today's events.")
async def uwu_command(interaction: discord.Interaction):
    await interaction.response.defer()
    prev_data = load_previous_events()
    all_events = prev_data.get(ALL_EVENTS_KEY, [])
    event_titles = get_today_event_titles(all_events)
    greeting_text = generate_greeting(event_titles)
    await interaction.followup.send(f"**UwU Greeting**\n{greeting_text}")
    prompt = generate_image_prompt(event_titles)
    try:
        img_path = await asyncio.to_thread(generate_image, prompt)
        await interaction.followup.send(file=discord.File(img_path))
    except Exception as e:
        await interaction.followup.send(f"[Error generating image] {e}")

if __name__ == "__main__":
    if not TOKEN:
        log.critical("DISCORD_BOT_TOKEN environment variable not set.")
        exit(1)
    bot.run(TOKEN)