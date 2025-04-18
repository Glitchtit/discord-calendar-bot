# ╔════════════════════════════════════════════════════════════════════════════╗
# ║                        CALENDAR BOT LOGGING SETUP                        ║
# ║    Provides a preconfigured logger for file and console output           ║
# ╚════════════════════════════════════════════════════════════════════════════╝

import logging
import sys
import platform
import atexit
import os
import tempfile
from logging.handlers import QueueHandler, QueueListener, MemoryHandler, TimedRotatingFileHandler
from datetime import datetime
from queue import Queue
from colorlog import ColoredFormatter
from utils.environ import DEBUG

LOG_DIR = "/data/logs"
LOG_FILE = os.path.join(LOG_DIR, "bot.log")
FALLBACK_DIRS = [
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs"),
    tempfile.gettempdir(),
]
active_log_file = None
log_dir_used = None

def setup_log_directory():
    global active_log_file, log_dir_used
    if os.access(os.path.dirname(LOG_DIR), os.W_OK):
        try:
            os.makedirs(LOG_DIR, exist_ok=True)
            if os.access(LOG_DIR, os.W_OK):
                active_log_file = LOG_FILE
                log_dir_used = LOG_DIR
                return True
        except Exception:
            pass
    for fallback in FALLBACK_DIRS:
        try:
            os.makedirs(fallback, exist_ok=True)
            test_file = os.path.join(fallback, "calendarbot.log")
            if os.access(fallback, os.W_OK):
                active_log_file = test_file
                log_dir_used = fallback
                print(f"Using fallback log directory: {fallback}")
                return True
        except Exception:
            continue
    print("WARNING: Could not find a writable log directory. Logging to file disabled.")
    return False

has_valid_log_dir = setup_log_directory()

# ╔════════════════════════════════════════════════════════════════════════════╗
# ║ LOGGER INITIALIZATION                                                     ║
# ╚════════════════════════════════════════════════════════════════════════════╝
logger = logging.getLogger("calendarbot")
logger.setLevel(logging.DEBUG if DEBUG else logging.INFO)
log_queue = Queue(-1)
queue_handler = QueueHandler(log_queue)
logger.addHandler(queue_handler)
if not getattr(logger, '_initialized', False):
    handlers = []
    try:
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
        if has_valid_log_dir:
            try:
                file_handler = TimedRotatingFileHandler(
                    active_log_file,
                    when="midnight",
                    interval=1,
                    backupCount=7,
                    encoding="utf-8",
                    delay=False
                )
                file_handler.maxBytes = 10 * 1024 * 1024
                file_handler.setFormatter(file_formatter)
                file_handler.setLevel(logging.DEBUG if DEBUG else logging.INFO)
                handlers.append(file_handler)
                memory_handler = MemoryHandler(
                    capacity=1000,
                    flushLevel=logging.ERROR,
                    target=file_handler
                )
                handlers.append(memory_handler)
                print(f"Logging to: {active_log_file}")
            except Exception as e:
                print(f"Error setting up file handler: {e}")
        else:
            print("File logging disabled due to permission issues")
        try:
            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setFormatter(console_formatter)
            console_handler.setLevel(logging.DEBUG if DEBUG else logging.INFO)
            handlers.append(console_handler)
        except Exception as e:
            print(f"Error setting up console handler: {e}")
            if not handlers:
                console_handler = logging.StreamHandler(sys.stdout)
                console_handler.setLevel(logging.WARNING)
                handlers.append(console_handler)
        listener = QueueListener(log_queue, *handlers, respect_handler_level=True)
        listener.start()
        logger._listener = listener
        logger._initialized = True
        def cleanup():
            try:
                for handler in handlers:
                    if isinstance(handler, MemoryHandler):
                        handler.flush()
                if hasattr(logger, '_listener'):
                    logger._listener.stop()
                print("Logging shutdown complete.")
            except Exception as e:
                print(f"Error during logging cleanup: {e}")
        atexit.register(cleanup)
        logger.info(f"Logging initialized ({platform.platform()}) at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info(f"Log level: {'DEBUG' if DEBUG else 'INFO'}")
        if has_valid_log_dir:
            logger.info(f"Log directory: {log_dir_used}")
        else:
            logger.warning("File logging disabled - using console only")
        logger.info("Server-specific configurations are now used. Tags have been deprecated.")
        logger.info("Ensure all calendars are mapped to user IDs via the /setup command.")
    except Exception as e:
        print(f"Critical error initializing logger: {e}")
        basic_handler = logging.StreamHandler(sys.stdout)
        basic_formatter = logging.Formatter('%(levelname)s: %(message)s')
        basic_handler.setFormatter(basic_formatter)
        logger.addHandler(basic_handler)

def get_log_file_location():
    return active_log_file if has_valid_log_dir else "Console only (no file)"
