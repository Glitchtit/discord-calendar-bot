# main.py

import os
import time
import asyncio
import schedule
import threading
import discord
from discord.ext import commands
from discord import app_commands

# -- Import from your local modules --
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

    # Attempt slash command sync
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} slash commands.")
    except Exception as e:
        print(f"Error syncing slash commands: {e}")

    # ------------------------------------------------
    # CHANGE: Immediately do an update on startup
    # so events.json + embeds.json are current.
    # ------------------------------------------------
    task_daily_update_and_check()

    # Start the scheduled tasks thread (so daily checks still happen)
    start_scheduling_thread()


def run_schedule_loop():
    """Runs in a separate thread to handle scheduled jobs."""
    while True:
        schedule.run_pending()
        time.sleep(30)


def start_scheduling_thread():
    """
    You can define your daily or periodic tasks here. For example:
      schedule.every().day.at("08:00").do(task_daily_update_and_check)
    Then launch them in a separate thread.
    """
    # Example: do a full sync every day at 08:00
    schedule.every().day.at("08:00").do(task_daily_update_and_check)

    t = threading.Thread(target=run_schedule_loop, daemon=True)
    t.start()


def task_daily_update_and_check():
    """
    1) Fetch all events from calendar sources.
    2) Detect changes vs. the old stored list.
    3) Update the vector store for any new or changed events.
    4) Optionally post changes and a catgirl greeting in a Discord channel.
    """
    channel = bot.get_channel(int(ANNOUNCEMENT_CHANNEL_ID)) if ANNOUNCEMENT_CHANNEL_ID else None
    if not channel:
        print("[WARN] Announcement channel not set or not accessible.")

    # 1) Fetch new list of *all* events
    new_events = get_all_calendar_events()

    # 2) Compare to old
    prev_data = load_previous_events()
    old_events = prev_data.get(ALL_EVENTS_KEY, [])

    changes = detect_changes(old_events, new_events)
    if changes:
        save_current_events_for_key(ALL_EVENTS_KEY, new_events)

        if channel:
            async def post_changes():
                # chunk the messages to avoid length issues
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
        # If no changes but we have no record yet, store them anyway
        if not old_events:
            save_current_events_for_key(ALL_EVENTS_KEY, new_events)

    # 3) Update embeddings in the store
    update_store_embeddings(old_events, new_events)

    # 4) (Optional) Post daily catgirl greeting
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
    """
    Removes any events no longer in the new list, then adds/updates
    embeddings for all new or changed events.
    """
    old_ids = {e["id"] for e in old_events}
    new_ids = {e["id"] for e in new_events}

    # Remove any events that disappeared
    for removed_id in (old_ids - new_ids):
        store.remove_event(removed_id)

    # Add/update all current events
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
