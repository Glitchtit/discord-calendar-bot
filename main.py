import os
import time
import asyncio
import schedule
import threading
import discord
from discord.ext import commands
from discord import app_commands

from calendar_tasks import (
    get_all_calendar_events,
    detect_changes,
    load_previous_events,
    save_current_events_for_key,
    format_event,
    ALL_EVENTS_KEY
)
from ai import store, ask_ai_any_question, generate_greeting, generate_image_prompt, generate_image

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

    # Instead of calling task_daily_update_and_check() directly,
    # run it in a background thread so the event loop isn’t blocked:
    def run_initial_sync():
        task_daily_update_and_check()

    threading.Thread(target=run_initial_sync, daemon=True).start()

    # Also start your scheduled tasks in another thread
    start_scheduling_thread()


def run_schedule_loop():
    while True:
        schedule.run_pending()
        time.sleep(30)


def start_scheduling_thread():
    # example: update daily at 08:00
    schedule.every().day.at("08:00").do(task_daily_update_and_check)
    t = threading.Thread(target=run_schedule_loop, daemon=True)
    t.start()


def task_daily_update_and_check():
    """
    1) Fetch all events.
    2) Detect changes.
    3) Update vector store.
    4) Optionally announce changes in a channel.
    """
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

            # Schedule on the main event loop
            asyncio.run_coroutine_threadsafe(post_changes(), bot.loop)
    else:
        # if no changes but empty store, save the new list
        if not old_events:
            save_current_events_for_key(ALL_EVENTS_KEY, new_events)

    # embed new events
    update_store_embeddings(old_events, new_events)

    # optional daily greeting
    if channel:
        async def post_daily_greeting():
            event_titles = [evt.get("summary", "mysterious event") for evt in new_events]
            greeting_text = generate_greeting(event_titles)
            await channel.send(greeting_text)
            try:
                prompt = generate_image_prompt(event_titles)
                img_path = generate_image(prompt)
                await channel.send(file=discord.File(img_path))
            except Exception as e:
                await channel.send(f"[Error generating image] {e}")

        asyncio.run_coroutine_threadsafe(post_daily_greeting(), bot.loop)


def update_store_embeddings(old_events, new_events):
    old_ids = {e["id"] for e in old_events}
    new_ids = {e["id"] for e in new_events}

    # remove vanished events
    for removed_id in (old_ids - new_ids):
        store.remove_event(removed_id)

    # add/update
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
        # This does a blocking openai.Embedding.create() call
        # but now in a background thread (not on the main event loop):
        store.add_or_update_event(eid, text_repr)


@bot.tree.command(name="ask", description="Ask the AI anything about your calendar or otherwise.")
@app_commands.describe(query="Your question or query.")
async def ask_command(interaction: discord.Interaction, query: str):
    await interaction.response.defer()
    answer = ask_ai_any_question(query, top_k=5)
    await interaction.followup.send(answer)


@bot.tree.command(name="uwu", description="Generate a cringe catgirl greeting referencing all known events.")
async def uwu_command(interaction: discord.Interaction):
    await interaction.response.defer()

    prev_data = load_previous_events()
    all_events = prev_data.get(ALL_EVENTS_KEY, [])
    event_titles = [e.get("summary", "mysterious event") for e in all_events]

    greeting_text = generate_greeting(event_titles)
    await interaction.followup.send(f"**UwU Greeting**\n{greeting_text}")

    try:
        prompt = generate_image_prompt(event_titles)
        img_path = generate_image(prompt)
        await interaction.followup.send(file=discord.File(img_path))
    except Exception as e:
        await interaction.followup.send(f"[Error generating image] {e}")


if __name__ == "__main__":
    if not TOKEN:
        print("Error: DISCORD_BOT_TOKEN environment variable not set.")
        exit(1)

    bot.run(TOKEN)
