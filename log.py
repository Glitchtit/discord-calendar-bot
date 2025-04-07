"""
log.py: Logging setup for the calendar bot.

Provides a 'logger' instance preconfigured with:
1. A colorized console handler for debug-level logs (if DEBUG is true).
2. A TimedRotatingFileHandler that rotates daily, keeping up to 14 days of logs.
3. Consistent formatting for both console and file output.

Usage:
    from log import logger
    logger.info("Hello, world!")
"""

import os
import logging
import os
import sys
import platform
import tempfile
from datetime import datetime
import atexit
from logging.handlers import TimedRotatingFileHandler, MemoryHandler
from logging.handlers import QueueHandler, QueueListener
import queue
from colorlog import ColoredFormatter
from environ import DEBUG

# ╔════════════════════════════════════════════════════════════════════╗
# 🔧 Directories & Filenames
# ╚════════════════════════════════════════════════════════════════════╝
# Primary log location
LOG_DIR = "/data/logs"
LOG_FILE = os.path.join(LOG_DIR, "bot.log")

# Fallback locations if primary is unavailable
FALLBACK_DIRS = [
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs"),  # Local logs directory
    tempfile.gettempdir(),  # System temp directory
]

# Find a valid log directory
active_log_file = None
log_dir_used = None

def setup_log_directory():
    global active_log_file, log_dir_used
    
    # Try primary location first
    if os.access(os.path.dirname(LOG_DIR), os.W_OK):
        try:
            os.makedirs(LOG_DIR, exist_ok=True)
            if os.access(LOG_DIR, os.W_OK):
                active_log_file = LOG_FILE
                log_dir_used = LOG_DIR
                return True
        except Exception:
            pass  # Will try fallbacks
    
    # Try fallback locations
    for fallback in FALLBACK_DIRS:
        try:
            os.makedirs(fallback, exist_ok=True)
            test_file = os.path.join(fallback, "calendarbot.log")
            
            # Test if we can write to this directory
            if os.access(fallback, os.W_OK):
                active_log_file = test_file
                log_dir_used = fallback
                print(f"Using fallback log directory: {fallback}")
                return True
        except Exception:
            continue
    
    # Could not find any valid directory
    print("WARNING: Could not find a writable log directory. Logging to file disabled.")
    return False

has_valid_log_dir = setup_log_directory()

# ╔════════════════════════════════════════════════════════════════════╗
# 🎨 Console Formatter & Handler
# ╚════════════════════════════════════════════════════════════════════╝
logger = logging.getLogger("calendarbot")
logger.setLevel(logging.DEBUG if DEBUG else logging.INFO)

# Create a logging queue for thread safety
log_queue = queue.Queue(-1)  # No limit on size
queue_handler = QueueHandler(log_queue)
logger.addHandler(queue_handler)

# Make sure we don't add multiple handlers
if getattr(logger, '_initialized', False):
    # Already initialized
    pass
else:
    handlers = []
    
    try:
        # File formatter: plain text logs with timestamps and extended data
        file_formatter = logging.Formatter(
            "[%(asctime)s] %(levelname)s in %(name)s [%(filename)s:%(lineno)d]: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )

        # Console formatter: colorful output for terminal debugging
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

        # File handler: logs everything to persistent storage with better rotation
        if has_valid_log_dir:
            try:
                # Use better rotation: daily + size-based with more history kept
                file_handler = TimedRotatingFileHandler(
                    active_log_file,
                    when="midnight",  # Rotate at midnight 
                    interval=1,       # One rotation per day
                    backupCount=7,    # Keep a week of logs
                    encoding="utf-8", # Prevent encoding issues
                    delay=False       # Create the file immediately
                )
                
                # Add size-based restrictions (10MB max)
                file_handler.maxBytes = 10 * 1024 * 1024
                
                file_handler.setFormatter(file_formatter)
                file_handler.setLevel(logging.DEBUG if DEBUG else logging.INFO)
                handlers.append(file_handler)
                
                # Add a buffered handler to protect against crashes
                memory_handler = MemoryHandler(
                    capacity=1000,          # Buffer up to 1000 records
                    flushLevel=logging.ERROR, # Flush immediately on errors
                    target=file_handler
                )
                handlers.append(memory_handler)
                
                # Log startup information
                print(f"Logging to: {active_log_file}")
            except Exception as e:
                print(f"Error setting up file handler: {e}")
                # Continue with console logging only
        else:
            print("File logging disabled due to permission issues")

        # Console handler: outputs to stdout for quick feedback
        try:
            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setFormatter(console_formatter)
            console_handler.setLevel(logging.DEBUG if DEBUG else logging.INFO)
            handlers.append(console_handler)
        except Exception as e:
            print(f"Error setting up console handler: {e}")
            # If even console logging fails, add a basic handler
            if not handlers:  # No handlers configured yet
                console_handler = logging.StreamHandler(sys.stdout)
                console_handler.setLevel(logging.WARNING)  # Only show warnings and errors
                handlers.append(console_handler)
        
        # Set up the queue listener with all handlers
        listener = QueueListener(log_queue, *handlers, respect_handler_level=True)
        listener.start()
        
        # Store for later access
        logger._listener = listener
        logger._initialized = True
        
        # Register cleanup for application exit
        def cleanup():
            try:
                # Flush memory handler if exists
                for handler in handlers:
                    if isinstance(handler, MemoryHandler):
                        handler.flush()
                
                # Stop the queue listener
                if hasattr(logger, '_listener'):
                    logger._listener.stop()
                    
                print("Logging shutdown complete.")
            except:
                pass
                
        atexit.register(cleanup)
        
        # Log initial startup information
        logger.info(f"Logging initialized ({platform.platform()}) at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info(f"Log level: {'DEBUG' if DEBUG else 'INFO'}")
        if has_valid_log_dir:
            logger.info(f"Log directory: {log_dir_used}")
        else:
            logger.warning("File logging disabled - using console only")
            
    except Exception as e:
        print(f"Critical error initializing logger: {e}")
        # Fall back to basic logging
        basic_handler = logging.StreamHandler(sys.stdout)
        basic_formatter = logging.Formatter('%(levelname)s: %(message)s')
        basic_handler.setFormatter(basic_formatter)
        logger.addHandler(basic_handler)

# Add a convenience function for log file location
def get_log_file_location():
    return active_log_file if has_valid_log_dir else "Console only (no file)"
