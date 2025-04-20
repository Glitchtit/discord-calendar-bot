# ╔════════════════════════════════════════════════════════════════════════════╗
# ║                        CALENDAR BOT LOGGING SETUP                        ║
# ║ Configures asynchronous, rotating file logging and colored console output. ║
# ║ Includes fallback mechanisms for log directory permissions.                ║
# ╚════════════════════════════════════════════════════════════════════════════╝

# Standard library imports
import logging
import sys
import platform
import atexit
import os
import tempfile
import traceback
from logging.handlers import QueueHandler, QueueListener, MemoryHandler, TimedRotatingFileHandler
from datetime import datetime
from queue import Queue

# Third-party imports
from colorlog import ColoredFormatter

# Local application imports
from utils.environ import DEBUG

# ╔════════════════════════════════════════════════════════════════════════════╗
# ║ LOGGING CONFIGURATION AND CONSTANTS                                        ║
# ╚════════════════════════════════════════════════════════════════════════════╝

# Preferred log directory (often mounted in Docker)
LOG_DIR = "/data/logs"
# Default log file name
LOG_FILE = os.path.join(LOG_DIR, "bot.log")

# Fallback directories if LOG_DIR is not writable
FALLBACK_DIRS = [
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs"), # Local logs dir
    tempfile.gettempdir(), # System temporary directory
]

# Variables to store the actual log file path and directory used
active_log_file = None
log_dir_used = None

# ╔════════════════════════════════════════════════════════════════════════════╗
# ║ LOG DIRECTORY SETUP                                                        ║
# ╚════════════════════════════════════════════════════════════════════════════╝

# --- setup_log_directory ---
# Attempts to create and verify write access to the log directory.
# Tries the preferred LOG_DIR first, then iterates through FALLBACK_DIRS.
# Sets `active_log_file` and `log_dir_used` globals upon success.
# Returns: True if a writable log directory was found and set up, False otherwise.
def setup_log_directory():
    global active_log_file, log_dir_used
    # --- Try Preferred Directory ---
    if os.access(os.path.dirname(LOG_DIR), os.W_OK):
        try:
            os.makedirs(LOG_DIR, exist_ok=True)
            if os.access(LOG_DIR, os.W_OK):
                active_log_file = LOG_FILE
                log_dir_used = LOG_DIR
                return True
        except Exception as e:
            # Log initial attempt failure (using print as logger might not be ready)
            print(f"Notice: Could not use preferred log directory {LOG_DIR}: {e}")
            pass # Continue to fallbacks

    # --- Try Fallback Directories ---
    for fallback in FALLBACK_DIRS:
        try:
            os.makedirs(fallback, exist_ok=True)
            # Use a consistent filename in fallback directories
            fallback_log_file = os.path.join(fallback, "calendarbot.log")
            # Test write access specifically to the directory
            if os.access(fallback, os.W_OK):
                active_log_file = fallback_log_file
                log_dir_used = fallback
                print(f"Using fallback log directory: {fallback}")
                return True
        except Exception as e:
            print(f"Notice: Could not use fallback log directory {fallback}: {e}")
            continue # Try next fallback

    # --- Failure Case ---
    print("CRITICAL WARNING: Could not find any writable log directory. File logging disabled.")
    return False

# --- Initialize Log Directory ---
# Call the setup function to determine the log path
has_valid_log_dir = setup_log_directory()

# ╔════════════════════════════════════════════════════════════════════════════╗
# ║ LOGGER INITIALIZATION AND CONFIGURATION                                    ║
# ╚════════════════════════════════════════════════════════════════════════════╝

# --- Get Root Logger ---
logger = logging.getLogger("calendarbot")
logger.setLevel(logging.DEBUG if DEBUG else logging.INFO)

# --- Asynchronous Logging Setup ---
# Use a queue for non-blocking logging
log_queue = Queue(-1) # Infinite queue size
queue_handler = QueueHandler(log_queue)
logger.addHandler(queue_handler)

# --- Prevent Re-initialization ---
# Check if logger has already been initialized in this process
if not getattr(logger, '_initialized', False):
    handlers = []
    try:
        # --- Define Formatters ---
        file_formatter = logging.Formatter(
            "[%(asctime)s] %(levelname)s in %(name)s [%(filename)s:%(lineno)d]: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        console_formatter = ColoredFormatter(
            "%(log_color)s[%(asctime)s] %(levelname)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
            log_colors={
                "DEBUG": "cyan",
                "INFO": "green",
                "WARNING": "yellow",
                "ERROR": "red",
                "CRITICAL": "bold_red",
            }
        )

        # --- Setup File Handler (if directory is valid) ---
        if has_valid_log_dir and active_log_file:
            try:
                # Rotating file handler (daily rotation, keeps 7 backups)
                file_handler = TimedRotatingFileHandler(
                    active_log_file,
                    when="midnight",
                    interval=1,
                    backupCount=7,
                    encoding="utf-8",
                    delay=False # Create log file immediately
                )
                # Note: TimedRotatingFileHandler doesn't directly support maxBytes.
                # If size-based rotation is needed, use RotatingFileHandler instead.
                # file_handler.maxBytes = 10 * 1024 * 1024 # Example if using RotatingFileHandler
                file_handler.setFormatter(file_formatter)
                file_handler.setLevel(logging.DEBUG if DEBUG else logging.INFO)

                # Memory handler buffers logs and flushes on error or capacity
                memory_handler = MemoryHandler(
                    capacity=1000, # Buffer up to 1000 records
                    flushLevel=logging.ERROR, # Flush when an ERROR or higher is logged
                    target=file_handler # Flush buffered records to the file handler
                )
                memory_handler.setLevel(logging.DEBUG) # Capture all levels in buffer
                handlers.append(memory_handler)
                print(f"File logging enabled: {active_log_file}")
            except Exception as e:
                print(f"ERROR: Failed to set up file logging handler: {e}")
                has_valid_log_dir = False # Disable file logging flag
        else:
            print("Notice: File logging is disabled.")

        # --- Setup Console Handler ---
        try:
            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setFormatter(console_formatter)
            console_handler.setLevel(logging.DEBUG if DEBUG else logging.INFO)
            handlers.append(console_handler)
        except Exception as e:
            print(f"ERROR: Failed to set up console logging handler: {e}")
            # Fallback to basic console logging if setup fails
            if not handlers:
                print("Warning: Falling back to basic console logging.")
                basic_handler = logging.StreamHandler(sys.stdout)
                basic_handler.setLevel(logging.WARNING)
                handlers.append(basic_handler)

        # --- Start Queue Listener ---
        # This listener pulls logs from the queue and sends them to actual handlers
        if handlers:
            listener = QueueListener(log_queue, *handlers, respect_handler_level=True)
            listener.start()
            logger._listener = listener # Store listener for cleanup
        else:
             print("CRITICAL: No logging handlers could be configured.")
             # Remove the queue handler if no listener could be started
             logger.removeHandler(queue_handler)

        # --- Mark as Initialized and Register Cleanup ---
        logger._initialized = True
        def cleanup():
            print("Shutting down logging...")
            try:
                # Ensure memory handler flushes remaining logs
                for handler in handlers:
                    if isinstance(handler, MemoryHandler):
                        handler.flush()
                        handler.close() # Close the target handler as well
                    elif hasattr(handler, 'close'):
                        handler.close()

                # Stop the listener thread
                if hasattr(logger, '_listener') and logger._listener:
                    logger._listener.stop()
                print("Logging shutdown complete.")
            except Exception as e:
                print(f"Error during logging cleanup: {e}")

        atexit.register(cleanup)

        # --- Initial Log Messages ---
        logger.info(f"--- Logging Initialized ({platform.system()} {platform.release()}) --- ")
        logger.info(f"Log Level: {'DEBUG' if DEBUG else 'INFO'}")
        if has_valid_log_dir and log_dir_used:
            logger.info(f"Log Directory: {log_dir_used}")
        else:
            logger.warning("File logging is disabled.")
        # Deprecation/Info messages
        logger.info("Using server-specific configurations (config/<server_id>/config.json).")
        logger.info("Ensure calendars are configured using /setup command.")

    except Exception as e:
        # --- Critical Initialization Failure ---
        print(f"CRITICAL ERROR during logger initialization: {e}")
        traceback.print_exc() # Print traceback for critical errors
        # Fallback to basic stdout logging if full setup fails
        if not getattr(logger, '_initialized', False):
            logger.handlers.clear() # Remove potentially broken handlers
            basic_handler = logging.StreamHandler(sys.stdout)
            basic_formatter = logging.Formatter('%(levelname)s: %(message)s')
            basic_handler.setFormatter(basic_formatter)
            logger.addHandler(basic_handler)
            logger.setLevel(logging.INFO)
            logger.critical("Logging system failed to initialize properly. Using basic console logging.")

# ╔════════════════════════════════════════════════════════════════════════════╗
# ║ UTILITY FUNCTIONS                                                          ║
# ╚════════════════════════════════════════════════════════════════════════════╝

# --- get_log_file_location ---
# Returns the path to the currently active log file.
# Returns: String containing the log file path, or a message indicating console-only logging.
def get_log_file_location():
    if has_valid_log_dir and active_log_file:
        return active_log_file
    else:
        return "Console only (File logging disabled)"
