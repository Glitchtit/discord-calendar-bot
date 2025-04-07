import logging
import os
from colorlog import ColoredFormatter
from environ import DEBUG

# ╔════════════════════════════════════════════════════════════════════╗
# ║ 📁 Log Directory & File Setup                                     ║
# ║ Creates the log directory if missing and defines log file path    ║
# ╚════════════════════════════════════════════════════════════════════╝
LOG_DIR = "/data/logs"
LOG_FILE = os.path.join(LOG_DIR, "bot.log")

try:
    os.makedirs(LOG_DIR, exist_ok=True)
except Exception as e:
    print(f"Error creating log directory: {e}")

# ╔════════════════════════════════════════════════════════════════════╗
# ║ 📋 Logger Initialization                                          ║
# ║ Sets up both console and file handlers with color and formatting  ║
# ╚════════════════════════════════════════════════════════════════════╝
logger = logging.getLogger("calendarbot")
logger.setLevel(logging.DEBUG if DEBUG else logging.INFO)

try:
    # Prevent multiple handlers from being added during reloads
    if not logger.handlers:
        # File formatter: plain text logs with timestamps
        file_formatter = logging.Formatter(
            "[%(asctime)s] %(levelname)s in %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )

        # Console formatter: colorful output for terminal debugging
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

        # File handler: logs everything to persistent storage
        try:
            file_handler = logging.FileHandler(LOG_FILE)
            file_handler.setFormatter(file_formatter)
            file_handler.setLevel(logging.DEBUG if DEBUG else logging.INFO)
            logger.addHandler(file_handler)
        except Exception as e:
            print(f"Error setting up file handler: {e}")

        # Console handler: outputs to stdout for quick feedback
        try:
            console_handler = logging.StreamHandler()
            console_handler.setFormatter(console_formatter)
            console_handler.setLevel(logging.DEBUG if DEBUG else logging.INFO)
            logger.addHandler(console_handler)
        except Exception as e:
            print(f"Error setting up console handler: {e}")
except Exception as e:
    print(f"Error initializing logger: {e}")
