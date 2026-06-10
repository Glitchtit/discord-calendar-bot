import sys
import os
import signal
import asyncio
import atexit
import threading
import time
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
# ║ 🔄 setup_watchdog                                                  ║
# ║ Sets up a watchdog thread to detect if the bot becomes stuck      ║
# ╚════════════════════════════════════════════════════════════════════╝
def setup_watchdog():
    """Set up a watchdog thread to monitor bot health."""
    def watchdog_thread():
        # Wait for initial startup period
        time.sleep(300)  # 5 minutes

        while not shutdown_in_progress:
            # bot.last_heartbeat is refreshed every 30s by the
            # verification_watchdog task, so it only advances while the
            # event loop is actually executing tasks. A stale value means
            # the loop is blocked/frozen even if the gateway looks alive.
            last_heartbeat = getattr(bot, 'last_heartbeat', None)
            if last_heartbeat and time.time() - last_heartbeat > 600:  # 10 minutes
                logger.warning(
                    f"Watchdog detected possible bot freeze - event loop heartbeat "
                    f"stale for {(time.time() - last_heartbeat) / 60:.0f} minutes"
                )

            # Sleep before next check
            time.sleep(60)  # Check every minute
    
    # Start watchdog in a daemon thread
    watchdog = threading.Thread(target=watchdog_thread, daemon=True)
    watchdog.start()
    logger.debug("Watchdog monitoring thread started")

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
        
        # Start watchdog monitoring
        setup_watchdog()
        
        # Configure Discord client with reconnect settings
        bot.max_reconnect_attempts = 10

        # Seed the event-loop liveness timestamp; the verification_watchdog
        # task in tasks.py refreshes it every 30 seconds once running.
        # (Note: registering on_resumed/on_heartbeat here would silently
        # replace bot.py's handlers — discord.py keys events by name.)
        bot.last_heartbeat = time.time()

        # Start the bot with reconnect enabled and retry logic
        logger.info("Starting Discord bot...")
        
        max_startup_retries = 3
        startup_retry_count = 0
        
        while startup_retry_count < max_startup_retries:
            try:
                bot.run(DISCORD_BOT_TOKEN, reconnect=True)
                break  # If we get here, the bot stopped normally
                
            except KeyboardInterrupt:
                logger.info("Bot shutdown requested by user")
                break
                
            except Exception as bot_error:
                startup_retry_count += 1
                
                # Check if this is a critical error that we shouldn't retry
                error_str = str(bot_error).lower()
                critical_errors = [
                    "improper token", "login failure", "unauthorized", 
                    "forbidden", "invalid token", "token is invalid"
                ]
                
                if any(critical in error_str for critical in critical_errors):
                    logger.error(f"Critical bot error - not retrying: {bot_error}")
                    break
                    
                if startup_retry_count < max_startup_retries:
                    retry_delay = min(30, 5 * (2 ** startup_retry_count))  # Exponential backoff, max 30s
                    logger.error(f"Bot crashed (attempt {startup_retry_count}/{max_startup_retries}): {bot_error}")
                    logger.info(f"Retrying in {retry_delay} seconds...")
                    time.sleep(retry_delay)
                else:
                    logger.error(f"Bot failed after {max_startup_retries} attempts: {bot_error}")
                    raise
        
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
