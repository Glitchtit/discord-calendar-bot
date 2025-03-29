import os
import logging
import colorlog

# Ensure log directory exists
os.makedirs("/data/logs", exist_ok=True)

# File log format
log_format = "%(asctime)s [%(levelname)s] %(message)s"
file_handler = logging.FileHandler("/data/logs/bot.log")
file_handler.setLevel(logging.DEBUG)
file_handler.setFormatter(logging.Formatter(log_format))

# Colorized console output
color_formatter = colorlog.ColoredFormatter(
    "%(log_color)s%(asctime)s [%(levelname)s]%(reset)s %(message)s",
    log_colors={
        'DEBUG': 'cyan',
        'INFO': 'green',
        'WARNING': 'yellow',
        'ERROR': 'red',
        'CRITICAL': 'bold_red',
    }
)
console_handler = colorlog.StreamHandler()
console_handler.setLevel(logging.DEBUG)
console_handler.setFormatter(color_formatter)

# Global logger instance
log = logging.getLogger("calendar-bot")
log.setLevel(logging.DEBUG)
log.handlers = [file_handler, console_handler]
