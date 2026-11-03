import sys
import os
import signal
import asyncio
import atexit
from types import FrameType
from typing import Optional

from bot import bot
from environ import (
    DISCORD_BOT_TOKEN, 
    ANNOUNCEMENT_CHANNEL_ID, 
    GOOGLE_APPLICATION_CREDENTIALS, 
    CALENDAR_SOURCES
)
from log import logger, get_log_file_location


# Flag to track if shutdown is in progress
shutdown_in_progress = False

# ╔════════════════════════════════════════════════════════════════════╗
# ║ 🔍 validate_environment                                            ║
# ║ Checks all required environment variables before startup          ║
# ╚════════════════════════════════════════════════════════════════════╝
def validate_environment() -> bool:
    """Validate that all required environment variables are set."""
    missing_vars = []
    
    # Check critical variables
    if not DISCORD_BOT_TOKEN:
        missing_vars.append("DISCORD_BOT_TOKEN")
    
    if not ANNOUNCEMENT_CHANNEL_ID:
        missing_vars.append("ANNOUNCEMENT_CHANNEL_ID")
    elif ANNOUNCEMENT_CHANNEL_ID == 0:
        logger.warning("ANNOUNCEMENT_CHANNEL_ID is set to default value (0). Bot may not post messages.")
        
    if not CALENDAR_SOURCES:
        missing_vars.append("CALENDAR_SOURCES")
    
    # Check if Google credentials file exists
    if not os.path.exists(GOOGLE_APPLICATION_CREDENTIALS):
        logger.error(f"Google credentials file not found: {GOOGLE_APPLICATION_CREDENTIALS}")
        missing_vars.append("GOOGLE_APPLICATION_CREDENTIALS (file not found)")
    
    if missing_vars:
        logger.error(f"Missing required environment variables: {', '.join(missing_vars)}")
        return False
        
    logger.info("Environment validation passed")
    return True

# ╔════════════════════════════════════════════════════════════════════╗
# ║ 🧹 cleanup                                                         ║
# ║ Performs cleanup operations before shutdown                       ║
# ╚════════════════════════════════════════════════════════════════════╝
def cleanup():
    """Perform cleanup operations when the bot is shutting down."""
    if not shutdown_in_progress:
        logger.info("Running cleanup operations...")
        
        # Any additional cleanup can be added here
        # For example, closing database connections, etc.
        
        logger.info("Cleanup complete")

# ╔════════════════════════════════════════════════════════════════════╗
# ║ 🛑 signal_handler                                                  ║
# ║ Handles system signals for graceful shutdown                      ║
# ╚════════════════════════════════════════════════════════════════════╝
def signal_handler(sig: int, frame: Optional[FrameType] = None) -> None:
    """Handle termination signals gracefully."""
    global shutdown_in_progress
    
    if shutdown_in_progress:
        # If we're already shutting down and get another signal,
        # exit immediately with a non-zero exit code
        logger.warning("Forced exit during shutdown")
        sys.exit(1)
    
    signal_name = signal.Signals(sig).name
    logger.info(f"Received {signal_name}, initiating graceful shutdown...")
    shutdown_in_progress = True
    
    # Schedule the bot to close
    if bot.is_ready():
        logger.info("Closing Discord bot connection...")
        if not asyncio.get_event_loop().is_closed():
            asyncio.create_task(bot.close())
    else:
        # If the bot isn't ready yet, we can exit more directly
        logger.info("Bot wasn't fully initialized, exiting...")
        sys.exit(0)

# ╔════════════════════════════════════════════════════════════════════╗
# ║ 📊 display_startup_info                                            ║
# ║ Logs useful information during startup                            ║
# ╚════════════════════════════════════════════════════════════════════╝
def display_startup_info():
    """Display information about the bot's configuration."""
    logger.info("========== Calendar Bot Starting ==========")
    logger.info(f"Python version: {sys.version}")
    logger.info(f"Log file: {get_log_file_location()}")
    logger.info(f"Working directory: {os.getcwd()}")
    
    # Calendar and environment info
    calendar_count = len(CALENDAR_SOURCES.split(",")) if CALENDAR_SOURCES else 0
    logger.info(f"Configured calendars: {calendar_count}")
    
    # Discord connection info
    logger.info("Discord connection: Establishing...")
    logger.info("======================================")

# ╔════════════════════════════════════════════════════════════════════╗
# ║ 🚀 main                                                            ║
# ║ Entry point for launching the Discord bot                         ║
# ║ Ensures environment variable is present before starting the bot   ║
# ╚════════════════════════════════════════════════════════════════════╝
def main():
    try:
        # Set up signal handlers for graceful termination
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        
        # Register cleanup handler
        atexit.register(cleanup)
        
        # Display startup information
        display_startup_info()
        
        # Validate environment variables
        if not validate_environment():
            logger.error("Environment validation failed. Exiting.")
            sys.exit(1)
        
        # One run: discord.py reconnects by itself, and a closed client can't be
        # restarted in-process, so on a fatal error we exit and let Docker restart us
        logger.info("Starting Discord bot...")
        bot.run(DISCORD_BOT_TOKEN, reconnect=True)
        
    except Exception as e:
        logger.exception(f"Critical error in main: {e}")
        sys.exit(1)
    finally:
        if not shutdown_in_progress:
            logger.info("Bot has stopped.")

# ╔════════════════════════════════════════════════════════════════════╗
# ║ 🧩 __main__ check                                                  ║
# ║ Allows script to be run directly (e.g., `python main.py`)         ║
# ╚════════════════════════════════════════════════════════════════════╝
if __name__ == "__main__":
    main()
