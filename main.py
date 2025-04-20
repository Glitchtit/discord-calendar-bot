# ╔════════════════════════════════════════════════════════════════════════════╗
# ║                         CALENDAR BOT MAIN ENTRYPOINT                     ║
# ║      Launches the Discord Calendar Bot and manages lifecycle events      ║
# ╚════════════════════════════════════════════════════════════════════════════╝

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
    GOOGLE_APPLICATION_CREDENTIALS
)
from utils.logging import logger, get_log_file_location
from config.server_config import get_all_server_ids

shutdown_in_progress = False

# ╔════════════════════════════════════════════════════════════════════════════╗
# ║ ENVIRONMENT VALIDATION                                                    ║
# ╚════════════════════════════════════════════════════════════════════════════╝

# --- validate_environment ---
# Checks if required environment variables (like DISCORD_BOT_TOKEN) are set.
# Logs warnings if no servers are configured yet.
# Returns: True if validation passes or only server config is missing, False otherwise.
def validate_environment() -> bool:
    missing_vars = []
    if not DISCORD_BOT_TOKEN:
        missing_vars.append("DISCORD_BOT_TOKEN")
    server_ids = get_all_server_ids()
    if not server_ids:
        logger.warning("No servers configured. Use /setup command after startup")
        return True
    if missing_vars:
        logger.error(f"Missing required environment variables: {', '.join(missing_vars)}")
        return False
    logger.info("Environment validation passed")
    return True

# ╔════════════════════════════════════════════════════════════════════════════╗
# ║ CLEANUP OPERATIONS                                                        ║
# ╚════════════════════════════════════════════════════════════════════════════╝

# --- cleanup ---
# Registered with atexit to run on script termination.
# Performs cleanup tasks, currently logs the start and end of cleanup.
def cleanup():
    if not shutdown_in_progress:
        logger.info("Running cleanup operations...")
        logger.info("Cleanup complete")

# ╔════════════════════════════════════════════════════════════════════════════╗
# ║ SIGNAL HANDLING                                                           ║
# ╚════════════════════════════════════════════════════════════════════════════╝

# --- signal_handler ---
# Handles termination signals (SIGINT, SIGTERM) for graceful shutdown.
# Sets the global shutdown_in_progress flag and attempts to close the bot connection.
# Args:
#     sig: The signal number received.
#     frame: The current stack frame (optional).
def signal_handler(sig: int, frame: Optional[FrameType] = None) -> None:
    global shutdown_in_progress
    if shutdown_in_progress:
        logger.warning("Forced exit during shutdown")
        sys.exit(1)
    signal_name = signal.Signals(sig).name
    logger.info(f"Received {signal_name}, initiating graceful shutdown...")
    shutdown_in_progress = True
    if bot.is_ready():
        logger.info("Closing Discord bot connection...")
        if not asyncio.get_event_loop().is_closed():
            asyncio.create_task(bot.close())
    else:
        logger.info("Bot wasn't fully initialized, exiting...")
        sys.exit(0)

# ╔════════════════════════════════════════════════════════════════════════════╗
# ║ WATCHDOG MONITORING                                                       ║
# ╚════════════════════════════════════════════════════════════════════════════╝

# --- setup_watchdog ---
# Initializes and starts a background thread to monitor the bot's health.
# The watchdog checks if the bot is responsive (based on heartbeats) periodically.
def setup_watchdog():
    def watchdog_thread():
        time.sleep(300)
        while not shutdown_in_progress:
            if not bot.is_closed() and bot.is_ready():
                pass
            else:
                if hasattr(bot, 'last_heartbeat') and time.time() - bot.last_heartbeat > 600:
                    logger.warning("Watchdog detected possible bot freeze - no heartbeat for 10 minutes")
            time.sleep(60)
    watchdog = threading.Thread(target=watchdog_thread, daemon=True)
    watchdog.start()
    logger.debug("Watchdog monitoring thread started")

# ╔════════════════════════════════════════════════════════════════════════════╗
# ║ STARTUP INFORMATION                                                       ║
# ╚════════════════════════════════════════════════════════════════════════════╝

# --- display_startup_info ---
# Logs essential information when the bot starts up, including Python version,
# log file location, working directory, and configured server IDs.
def display_startup_info():
    import sys
    import os
    from config.server_config import get_all_server_ids
    logger.info("========== Calendar Bot Starting ==========")
    logger.info(f"Python version: {sys.version}")
    logger.info(f"Log file: {get_log_file_location()}")
    logger.info(f"Working directory: {os.getcwd()}")
    server_ids = get_all_server_ids()
    logger.info(f"Configured servers: {len(server_ids)}")
    if server_ids:
        logger.info(f"Server IDs: {', '.join(str(sid) for sid in server_ids)}")
    else:
        logger.warning("No servers configured. Use /setup to add calendars.")
    logger.info("Discord connection: Establishing...")
    logger.info("======================================")

# ╔════════════════════════════════════════════════════════════════════════════╗
# ║ MAIN ENTRYPOINT                                                           ║
# ╚════════════════════════════════════════════════════════════════════════════╝

# --- main ---
# The main execution function of the bot.
# Sets up signal handling, registers cleanup, displays startup info,
# validates the environment, starts the watchdog, and runs the Discord bot.
# Handles critical errors during startup.
def main():
    try:
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        atexit.register(cleanup)
        display_startup_info()
        if not validate_environment():
            logger.error("Environment validation failed. Exiting.")
            sys.exit(1)
        setup_watchdog()
        bot.max_reconnect_attempts = 10
        bot.last_heartbeat = time.time()
        bot.is_initialized = False
        logger.info("Starting Discord bot...")
        bot.run(DISCORD_BOT_TOKEN, reconnect=True)
    except Exception as e:
        logger.exception(f"Critical error in main: {e}")
        sys.exit(1)
    finally:
        if not shutdown_in_progress:
            logger.info("Bot has stopped.")

# ╔════════════════════════════════════════════════════════════════════════════╗
# ║ SCRIPT EXECUTION CHECK                                                    ║
# ╚════════════════════════════════════════════════════════════════════════════╝
if __name__ == "__main__":
    main()
