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
from date_utils import extract_date_range_from_query
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

    def run_initial_sync():
        log.info("[Startup] Performing initial calendar sync and embedding...")
        task_daily_update_and_check()

    threading.Thread(target=run_initial_sync, daemon=True).start()
    start_scheduling_thread()

def run_schedule_loop():
    while True:
        schedule.run_pending()
        time.sleep(30)

def start_scheduling_thread():
    schedule.every().day.at("08:00").do(task_daily_update_and_check)
    t = threading.Thread(target=run_schedule_loop, daemon=True)
    t.start()

def task_daily_update_and_check():
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
            asyncio.run_coroutine_threadsafe(post_changes(), bot.loop)
    else:
        log.info("[Sync] No calendar changes found.")
        if not old_events:
            log.info("[Sync] No previous event snapshot — saving current events.")
            save_current_events_for_key(ALL_EVENTS_KEY, new_events)

    before_count = len(store.get_all_event_ids())
    update_store_embeddings(old_events, new_events)
    after_count = len(store.get_all_event_ids())
    log.info(f"[Sync] Embedding store now contains {after_count} events (was {before_count}, net change: {after_count - before_count}).")

    if channel:
        async def post_daily_greeting():
            event_titles = get_today_event_titles(new_events)
            greeting_text = generate_greeting(event_titles)
            await channel.send(greeting_text)
            prompt = generate_image_prompt(event_titles)
            try:
                img_path = await asyncio.to_thread(generate_image, prompt)
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
        text_repr = f"Title: {summary}\nStart: {start}\nEnd: {end}\nLocation: {loc}\nDesc: {desc}"
        store.add_or_update_event(eid, text_repr)

@bot.tree.command(name="ask", description="Ask the AI anything about your calendar or otherwise.")
@app_commands.describe(query="Your question or query.")
async def ask_command(interaction: discord.Interaction, query: str):
    await interaction.response.defer()
    message = await interaction.followup.send("🔮 Summoning an answer...")

    try:
        all_events = load_previous_events().get(ALL_EVENTS_KEY, [])
        date_range = extract_date_range_from_query(query)

        if date_range:
            start_dt, end_dt = date_range
            log.debug(f"[Query] Filtering events from {start_dt} to {end_dt}")

            def is_within_range(event):
                start_str = event["start"].get("dateTime") or event["start"].get("date")
                if "T" in start_str:
                    dt = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
                else:
                    dt = datetime.fromisoformat(start_str).replace(hour=0, minute=0, second=0, tzinfo=tz.tzlocal())
                dt_local = dt.astimezone(tz.tzlocal())
                return start_dt <= dt_local <= end_dt

            filtered_events = list(filter(is_within_range, all_events))
        else:
            filtered_events = all_events

        # Optional: tag-based filtering (e.g. "Thomas's events")
        query_lower = query.lower()
        if "thomas" in query_lower:
            filtered_events = [e for e in filtered_events if e.get("tag", "").upper() in {"T", "B"}]
        elif "anniina" in query_lower:
            filtered_events = [e for e in filtered_events if e.get("tag", "").upper() in {"A", "B"}]

        temp_store = EventEmbeddingStore()
        for e in filtered_events:
            eid = e["id"]
            summary = e.get("summary", "")
            start = e["start"].get("dateTime") or e["start"].get("date", "")
            end = e["end"].get("dateTime") or e["end"].get("date", "")
            loc = e.get("location", "")
            desc = e.get("description", "")
            text_repr = f"Title: {summary}\nStart: {start}\nEnd: {end}\nLocation: {loc}\nDesc: {desc}"
            temp_store.add_or_update_event(eid, text_repr)

        top_events = temp_store.query(query, top_k=5)

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