import discord
from discord.ext import commands
from discord import app_commands
from datetime import datetime, timedelta
import asyncio
import os

# Import from new refactored structure
from src.core.logger import logger
from src.core.environment import DISCORD_BOT_TOKEN, ANNOUNCEMENT_CHANNEL_ID, AI_TOGGLE
from src.calendar.sources import load_calendar_sources, get_user_tag_mapping
from src.calendar.events import get_events
from src.calendar.storage import load_previous_events, save_current_events_for_key
from src.ai.generator import generate_greeting, generate_image
from src.ai.title_parser import simplify_event_title
from src.discord_bot.commands import setup_commands
from src.discord_bot.embeds import create_announcement_embed
from src.scheduling import get_scheduler
from src.utils import get_date_range, cleanup_old_files

# ╔════════════════════════════════════════════════════════════════════╗
# ║ 🤖 Discord Bot Initialization                                     ║
# ║ Configures the bot with necessary intents and modern architecture ║
# ╚════════════════════════════════════════════════════════════════════╝

intents = discord.Intents.default()
intents.members = True
intents.message_content = True  # Required for some Discord features
bot = commands.Bot(command_prefix="/", intents=intents)

# Track initialization state to avoid duplicate startups
bot.is_initialized = False
bot.announcement_channel = None

# ╔════════════════════════════════════════════════════════════════════╗
# ║ 🟢 Bot Event Handlers                                              ║
# ╚════════════════════════════════════════════════════════════════════╝

@bot.event
async def on_ready():
    """Called when the bot is ready and connected to Discord."""
    logger.info(f"Bot logged in as {bot.user} (ID: {bot.user.id})")
    
    # Prevent multiple initializations on reconnects
    if bot.is_initialized:
        logger.info("Bot reconnected, skipping initialization")
        return
    
    try:
        # Get announcement channel
        if ANNOUNCEMENT_CHANNEL_ID:
            bot.announcement_channel = bot.get_channel(ANNOUNCEMENT_CHANNEL_ID)
            if bot.announcement_channel:
                logger.info(f"Found announcement channel: #{bot.announcement_channel.name}")
            else:
                logger.warning(f"Announcement channel {ANNOUNCEMENT_CHANNEL_ID} not found")
        
        # Set up bot commands
        await setup_commands(bot)
        
        # Resolve tag mappings for display names
        from src.discord_bot.commands import resolve_tag_mappings
        await resolve_tag_mappings(bot)
        
        # Sync slash commands
        try:
            synced = await bot.tree.sync()
            logger.info(f"Synced {len(synced)} slash commands")
        except Exception as e:
            logger.error(f"Failed to sync commands: {e}")
        
        # Initialize calendar data
        calendar_sources = load_calendar_sources()
        logger.info(f"Loaded {len(calendar_sources)} calendar source groups")
        
        # Set up scheduled tasks
        scheduler = get_scheduler()
        scheduler.schedule_daily_task("daily_announcement", daily_announcement_task, hour=8, minute=0)
        scheduler.schedule_daily_task("cleanup_task", cleanup_task, hour=2, minute=0)
        
        # Mark as initialized
        bot.is_initialized = True
        logger.info("Bot initialization completed successfully")
        
    except Exception as e:
        logger.exception(f"Error during bot initialization: {e}")
        bot.is_initialized = True  # Prevent retry loops

@bot.event
async def on_disconnect():
    """Called when the bot disconnects from Discord."""
    logger.warning("Bot disconnected from Discord")

@bot.event
async def on_resumed():
    """Called when the bot reconnects to Discord."""
    logger.info("Bot connection resumed")

@bot.event
async def on_command_error(ctx, error):
    """Handle command errors."""
    logger.error(f"Command error in {ctx.command}: {error}")

# ╔════════════════════════════════════════════════════════════════════╗
# ║ 📅 Daily Announcement Task                                         ║
# ╚════════════════════════════════════════════════════════════════════╝

async def daily_announcement_task():
    """Generate and post daily calendar announcements."""
    try:
        if not bot.announcement_channel:
            logger.warning("No announcement channel configured, skipping daily announcement")
            return
        
        logger.info("Starting daily announcement task")
        
        # Get today's events from all calendar sources
        calendar_sources = load_calendar_sources()
        start_date, end_date = get_date_range(days=3)  # Look ahead 3 days
        
        all_events = []
        event_titles = []
        
        for tag, sources in calendar_sources.items():
            for source in sources:
                try:
                    events = get_events(source, start_date.date(), end_date.date())
                    all_events.extend(events)
                    
                    # Collect titles for greeting generation
                    for event in events:
                        title = event.get('summary', 'Event')
                        if title not in event_titles:
                            event_titles.append(title)
                            
                except Exception as e:
                    logger.warning(f"Error fetching events from {source.get('name', 'unknown')}: {e}")
        
        # Get present users for greeting
        present_users = []
        if bot.announcement_channel.guild:
            user_tag_mapping = get_user_tag_mapping()
            for user_id in user_tag_mapping.keys():
                try:
                    member = bot.announcement_channel.guild.get_member(user_id)
                    if member and member.status != discord.Status.offline:
                        present_users.append(member.display_name)
                except Exception:
                    pass
        
        # Generate greeting and image if AI is enabled
        greeting = None
        persona = "Royal Messenger"
        image_path = None
        
        if AI_TOGGLE:
            try:
                greeting, persona = generate_greeting(event_titles[:5], present_users)  # Limit titles
                if greeting:
                    image_path = generate_image(greeting, persona)
            except Exception as e:
                logger.warning(f"Error generating AI content: {e}")
        
        # Use fallback greeting if AI failed
        if not greeting:
            today = datetime.now().strftime("%A, %B %d")
            if event_titles:
                greeting = f"Good morrow! On this {today}, {len(event_titles)} events await thy attention."
            else:
                greeting = f"Good morrow! On this {today}, thy calendar is free for noble pursuits."
            greeting += f"\n\n— {persona}"
        
        # Create and send announcement
        embed = create_announcement_embed(greeting, all_events, persona)
        
        # Send the message
        files = []
        if image_path and os.path.exists(image_path):
            try:
                files.append(discord.File(image_path, filename="daily_greeting.png"))
                embed.set_image(url="attachment://daily_greeting.png")
            except Exception as e:
                logger.warning(f"Error attaching image: {e}")
        
        await bot.announcement_channel.send(embed=embed, files=files)
        logger.info("Daily announcement posted successfully")
        
    except Exception as e:
        logger.exception(f"Error in daily announcement task: {e}")

# ╔════════════════════════════════════════════════════════════════════╗
# ║ 🧹 Cleanup Task                                                    ║
# ╚════════════════════════════════════════════════════════════════════╝

async def cleanup_task():
    """Clean up old files and logs."""
    try:
        logger.info("Starting cleanup task")
        
        # Clean up old generated images
        image_dirs = ["/data/art", "art", "src/art"]
        for img_dir in image_dirs:
            if os.path.exists(img_dir):
                deleted = cleanup_old_files(img_dir, max_age_days=7, pattern="generated_*.png")
                if deleted > 0:
                    logger.info(f"Cleaned up {deleted} old images from {img_dir}")
        
        # Clean up old log files
        log_dirs = ["/data/logs", "logs"]
        for log_dir in log_dirs:
            if os.path.exists(log_dir):
                deleted = cleanup_old_files(log_dir, max_age_days=14, pattern="*.log.*")
                if deleted > 0:
                    logger.info(f"Cleaned up {deleted} old log files from {log_dir}")
        
        logger.info("Cleanup task completed")
        
    except Exception as e:
        logger.exception(f"Error in cleanup task: {e}")

# ╔════════════════════════════════════════════════════════════════════╗
# ║ 🏃 Bot Startup                                                     ║
# ╚════════════════════════════════════════════════════════════════════╝

async def main():
    """Main bot startup function."""
    try:
        if not DISCORD_BOT_TOKEN:
            logger.error("DISCORD_BOT_TOKEN not set in environment variables")
            return
        
        logger.info("Starting Discord Calendar Bot...")
        
        # Start the bot
        async with bot:
            await bot.start(DISCORD_BOT_TOKEN)
            
    except Exception as e:
        logger.exception(f"Error starting bot: {e}")
    finally:
        # Clean up scheduled tasks
        scheduler = get_scheduler()
        scheduler.stop_all_tasks()
        logger.info("Bot shutdown complete")

if __name__ == "__main__":
    # Run the bot
    asyncio.run(main())
