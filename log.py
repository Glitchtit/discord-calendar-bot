import os
import logging
from logging.handlers import TimedRotatingFileHandler
from colorlog import ColoredFormatter

# ╔════════════════════════════════════════════════════════════════════╗
# 🔧 Configuration
# ╚════════════════════════════════════════════════════════════════════╝
LOG_DIR = "/data/logs"
LOG_FILE = os.path.join(LOG_DIR, "bot.log")
DEBUG = os.environ.get("DEBUG", "false").lower() in ("1", "true", "yes")

os.makedirs(LOG_DIR, exist_ok=True)

# ╔════════════════════════════════════════════════════════════════════╗
# 🎨 Console Formatter
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
logger = logging.getLogger("calendarbot")
logger.setLevel(logging.DEBUG if DEBUG else logging.INFO)
logger.handlers.clear()
logger.addHandler(console_handler)
logger.addHandler(file_handler)
logger.propagate = False

logger.debug("Logger initialized. DEBUG=%s", DEBUG)
