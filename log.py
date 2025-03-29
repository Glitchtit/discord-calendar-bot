import logging
import os
from colorlog import ColoredFormatter

LOG_DIR = "/data/logs"
LOG_FILE = os.path.join(LOG_DIR, "bot.log")

# Ensure log directory exists
os.makedirs(LOG_DIR, exist_ok=True)

# Console formatter (colored)
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

# File formatter (plain)
file_formatter = logging.Formatter(
    "[%(asctime)s] %(levelname)s in %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

# File handler
file_handler = logging.FileHandler(LOG_FILE)
file_handler.setFormatter(file_formatter)

# Console handler (color)
console_handler = logging.StreamHandler()
console_handler.setFormatter(console_formatter)

# Root logger
logger = logging.getLogger("calendarbot")
logger.setLevel(logging.DEBUG)
logger.addHandler(console_handler)
logger.addHandler(file_handler)

# Make sure other modules propagate correctly
logging.getLogger().setLevel(logging.DEBUG)
logging.getLogger().addHandler(console_handler)
logging.getLogger().addHandler(file_handler)
