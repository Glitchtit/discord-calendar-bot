import sys
import os
import signal
import asyncio
import atexit
import threading
import time
from types import FrameType
from typing import Optional

from bot.core import bot
from utils.environ import (
    DISCORD_BOT_TOKEN, 
    ANNOUNCEMENT_CHANNEL_ID, 
    GOOGLE_APPLICATION_CREDENTIALS
)
from utils.logging import logger, get_log_file_location
from config.server_config import get_all_server_ids

# Flag to track if shutdown is in progress
shutdown_in_progress = False

# ╔════════════════════════════════════════════════════════════════════╗
# ║ 🔍 validate_environment                                            ║
# ║ Checks all required environment variables before startup          ║
# ╚════════════════════════════════════════════════════════════════════╝
def validate_environment() -> bool:
    """
    Validate that all required environment variables are set.
    
    Note: Calendar configuration is now done through the /setup command
    in Discord rather than through environment variables.
    """
    missing_vars = []
    
    # Check critical variables
    if not DISCORD_BOT_TOKEN:
        missing_vars.append("DISCORD_BOT_TOKEN")
    
    # Check server configurations instead of environment variables
    server_ids = get_all_server_ids()
    if not server_ids:
        logger.warning("No servers configured. Use /setup command after startup")
        return True  # Allow bot to start for initial setup
    
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
            # Check if event loop is still responsive
            if not bot.is_closed() and bot.is_ready():
                # Bot is still running normally
                pass
            else:
                # Only log issues after a reasonable time 
                if hasattr(bot, 'last_heartbeat') and time.time() - bot.last_heartbeat > 600:  # 10 minutes
                    logger.warning("Watchdog detected possible bot freeze - no heartbeat for 10 minutes")
            
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
    """
    Display information about the bot's configuration.
    
    Reports on server-specific configurations created with
    the /setup command rather than environment variables.
    """
    import sys
    import os
    from config.server_config import get_all_server_ids
    
    logger.info("========== Calendar Bot Starting ==========")
    logger.info(f"Python version: {sys.version}")
    logger.info(f"Log file: {get_log_file_location()}")
    logger.info(f"Working directory: {os.getcwd()}")
    
    # Calendar configuration info using server configs
    server_ids = get_all_server_ids()
    logger.info(f"Configured servers: {len(server_ids)}")
    if server_ids:
        logger.info(f"Server IDs: {', '.join(str(sid) for sid in server_ids)}")
    else:
        logger.warning("No servers configured. Use /setup to add calendars.")
    
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
        
        # Track last heartbeat for monitoring
        bot.last_heartbeat = time.time()
        
        # Reset initialization flag when starting fresh
        bot.is_initialized = False
        
        # Start the bot with reconnect enabled
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
