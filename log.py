import logging
import os
from colorlog import ColoredFormatter
from environ import DEBUG

LOG_DIR = "/data/logs"
LOG_FILE = os.path.join(LOG_DIR, "bot.log")
os.makedirs(LOG_DIR, exist_ok=True)

logger = logging.getLogger("calendarbot")
logger.setLevel(logging.DEBUG if DEBUG else logging.INFO)

if not logger.handlers:
    file_formatter = logging.Formatter(
        "[%(asctime)s] %(levelname)s in %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

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

    file_handler = logging.FileHandler(LOG_FILE)
    file_handler.setFormatter(file_formatter)
    file_handler.setLevel(logging.DEBUG if DEBUG else logging.INFO)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(console_formatter)
    console_handler.setLevel(logging.DEBUG if DEBUG else logging.INFO)

    logger.addHandler(console_handler)
    logger.addHandler(file_handler)
