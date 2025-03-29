import logging
import os
from colorlog import ColoredFormatter

# Directory and file path for logs
LOG_DIR = "/data/logs"
LOG_FILE = os.path.join(LOG_DIR, "bot.log")

# Ensure the log directory exists
os.makedirs(LOG_DIR, exist_ok=True)

# Create the logger
logger = logging.getLogger("calendarbot")
logger.setLevel(logging.DEBUG)

# Prevent adding handlers multiple times
if not logger.handlers:

    # File formatter (plain text)
    file_formatter = logging.Formatter(
        "[%(asctime)s] %(levelname)s in %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # Console formatter (colored output)
    console_formatter = ColoredFormatter(
        "%(log_color)s[%(asctime)s] %(levelname)s in %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        log_colors={
            "DEBUG": "cyan",
            "INFO": "green",
            "WARNING": "yellow",
            "ERROR": "red",
            "CRITICAL": "bold_red",
        }
    )

    # File handler
    file_handler = logging.FileHandler(LOG_FILE)
    file_handler.setFormatter(file_formatter)

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(console_formatter)

    # Attach handlers to the logger
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
