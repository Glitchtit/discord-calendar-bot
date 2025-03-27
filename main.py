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
# 'calendar_tasks' is where you have get_all_calendar_events(), detect_changes, etc.
# Adjust as needed if you named it differently.
from calendar_tasks import (
    get_all_calendar_events,
    detect_changes,
    load_previous_events,
    save_current_events_for_key,
    format_event,
    ALL_EVENTS_KEY  # or whatever key you use for storing "all" events
)

# 'ai' is where you have your vector store (store), ask_ai_any_question, and the uwu greeting logic.
from ai import store, ask_ai_any_question, generate_greeting, generate_image_prompt, generate_image

TOKEN = os.environ.get("DISCORD_BOT_TOKEN", "")
ANNOUNCEMENT_CHANNEL_ID = os.environ.get("ANNOUNCEMENT_CHANNEL_ID", "")

# If you have a JSON key in events.json or similar
# that holds the entire event list. We'll call it ALL_EVENTS_KEY by default.

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

    # Start a background thread to run scheduled tasks
    start_scheduling_thread()


# -------------------------------------------------
# SCHEDULING: DAILY OR PERIODIC CALENDAR SYNC
# -------------------------------------------------
def run_schedule_loop():
    """Runs in a separate thread to handle scheduled jobs."""
    while True:
        schedule.run_pending()
        time.sleep(30)  # check every 30 seconds


def start_scheduling_thread():
    """
    Define scheduled tasks, then start the scheduling thread.
    For example, fetch + update embeddings each morning, check for changes, etc.
    """
    # e.g. every day at 08:00
    schedule.every().day.at("08:00").do(task_daily_update_and_check)
    # Adjust or add additional schedules as needed

    t = threading.Thread(target=run_schedule_loop, daemon=True)
    t.start()


def task_daily_update_and_check():
    """
    1) Fetch all events from calendar sources.
    2) Detect changes vs. the old stored list.
    3) Update the vector store for any new or changed events.
    4) Optionally post changes or an "uwu greeting" in a channel.
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
        # Save new
        save_current_events_for_key(ALL_EVENTS_KEY, new_events)
        # Post changes if we have a channel
        if channel:
            async def post_changes():
                # We'll chunk them in case they're large
                chunk_size = 1800  # keep under 2000 char limit
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
        # If no changes, but we have no record yet, store them anyway
        if not old_events:
            save_current_events_for_key(ALL_EVENTS_KEY, new_events)

    # 3) Update embeddings in the store for any new or modified events
    #    We'll do a naive pass: if an event's ID is new or changed, we embed it.
    #    For real usage, you might compare old vs. new in detail.
    #    Or simply re-embed everything if your calendar isn't huge.
    update_store_embeddings(old_events, new_events)

    # 4) (Optional) Post a daily catgirl greeting
    if channel:
        async def post_daily_greeting():
            # We'll pass in the 'summary' of each new event as a list of titles
            event_titles = [evt.get("summary", "mysterious event") for evt in new_events]
            greeting_text = generate_greeting(event_titles)
            await channel.send(greeting_text)
            # Optionally generate an image
            prompt = generate_image_prompt(event_titles)
            try:
                img_path = generate_image(prompt)
                await channel.send(file=discord.File(img_path))
            except Exception as e:
                await channel.send(f"[Error generating image] {e}")

        asyncio.run_coroutine_threadsafe(post_daily_greeting(), bot.loop)


def update_store_embeddings(old_events, new_events):
    """
    Compares old vs new event lists, updates or adds embeddings in the global store.
    Removes embeddings for events that no longer exist.
    
    For a simpler approach, you could always re-embed all 'new_events', but
    this version tries to do minimal changes.
    """
    old_ids = {e["id"] for e in old_events}
    new_ids = {e["id"] for e in new_events}

    # Removed events
    for removed_id in (old_ids - new_ids):
        store.remove_event(removed_id)

    # For events that are new or possibly changed
    for evt in new_events:
        eid = evt["id"]
        # Build text representation
        summary = evt.get("summary", "")
        start = evt["start"].get("dateTime") or evt["start"].get("date", "")
        end = evt["end"].get("dateTime") or evt["end"].get("date", "")
        loc = evt.get("location", "")
        desc = evt.get("description", "")
        text_repr = f"Title: {summary}\nStart: {start}\nEnd: {end}\nLocation: {loc}\nDesc: {desc}"

        if eid not in old_ids:
            # definitely new
            store.add_or_update_event(eid, text_repr)
        else:
            # might have changed
            # We'll compare the text representation for differences, or just always embed:
            # For brevity, let's just always re-embed to ensure it's up to date
            store.add_or_update_event(eid, text_repr)


# -------------------------------------------------
# SLASH COMMANDS
# -------------------------------------------------

@bot.tree.command(name="ask", description="Ask the AI anything about your calendar or otherwise.")
@app_commands.describe(query="Your question or query.")
async def ask_command(interaction: discord.Interaction, query: str):
    """
    A slash command that uses the embedding store + GPT to answer questions.
    e.g. /ask "When is the board meeting?"
    """
    await interaction.response.defer()  # let user know we're processing
    answer = ask_ai_any_question(query, top_k=5)
    await interaction.followup.send(answer)


@bot.tree.command(name="uwu", description="Generate a cringe catgirl greeting referencing all known events.")
async def uwu_command(interaction: discord.Interaction):
    """
    A slash command that calls generate_greeting(...) and generate_image(...) for the entire set of events.
    """
    await interaction.response.defer()

    # Load your entire event list from storage
    prev_data = load_previous_events()
    all_events = prev_data.get(ALL_EVENTS_KEY, [])
    event_titles = [e.get("summary", "mysterious event") for e in all_events]

    greeting_text = generate_greeting(event_titles)
    await interaction.followup.send(f"**UwU Greeting**\n{greeting_text}")

    # Optionally produce an image
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
