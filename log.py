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
from logging.handlers import TimedRotatingFileHandler
from typing import Final

from colorlog import ColoredFormatter
from environ import DEBUG

# ╔════════════════════════════════════════════════════════════════════╗
# 🔧 Directories & Filenames
# ╚════════════════════════════════════════════════════════════════════╝
LOG_DIR: Final[str] = "/data/logs"
LOG_FILE: Final[str] = os.path.join(LOG_DIR, "bot.log")

os.makedirs(LOG_DIR, exist_ok=True)

# ╔════════════════════════════════════════════════════════════════════╗
# 🎨 Console Formatter & Handler
# ╚════════════════════════════════════════════════════════════════════╝
color_formatter = ColoredFormatter(
    fmt="%(log_color)s[%(asctime)s] [%(levelname)-8s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
    log_colors={
        "DEBUG":    "cyan",
        "INFO":     "green",
        "WARNING":  "yellow",
        "ERROR":    "red",
        "CRITICAL": "bold_red",
    }
)

console_handler = logging.StreamHandler()
console_handler.setLevel(logging.DEBUG if DEBUG else logging.INFO)
console_handler.setFormatter(color_formatter)

# ╔════════════════════════════════════════════════════════════════════╗
# 🗃️ File Handler with Daily Rotation
# ╚════════════════════════════════════════════════════════════════════╝
file_formatter = logging.Formatter(
    fmt="[%(asctime)s] [%(levelname)-8s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

file_handler = TimedRotatingFileHandler(
    LOG_FILE,
    when="midnight",
    interval=1,
    backupCount=14,
    encoding="utf-8",
    utc=True
)
file_handler.setLevel(logging.DEBUG if DEBUG else logging.INFO)
file_handler.setFormatter(file_formatter)

# ╔════════════════════════════════════════════════════════════════════╗
# 🧱 Logger Setup
# ╚════════════════════════════════════════════════════════════════════╝
logger: logging.Logger = logging.getLogger("calendarbot")
logger.setLevel(logging.DEBUG if DEBUG else logging.INFO)

# Clear any existing handlers to avoid duplication
logger.handlers.clear()

# Attach our two handlers
logger.addHandler(console_handler)
logger.addHandler(file_handler)

# Prevent messages from propagating to the root logger
logger.propagate = False

logger.debug(f"Logger initialized. DEBUG={DEBUG}")
