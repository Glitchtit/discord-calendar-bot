import logging
import os

LOG_DIR = "/data/logs"
LOG_FILE = os.path.join(LOG_DIR, "bot.log")

# Create log directory
os.makedirs(LOG_DIR, exist_ok=True)

# Create formatter
formatter = logging.Formatter(
    "[%(asctime)s] %(levelname)s in %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

# Create file handler
file_handler = logging.FileHandler(LOG_FILE)
file_handler.setFormatter(formatter)

# Create console handler (optional, useful for dev)
console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)

# Create root logger
logger = logging.getLogger("calendarbot")
logger.setLevel(logging.DEBUG)
logger.addHandler(file_handler)
logger.addHandler(console_handler)

# Ensure propagation to root from submodules
logging.getLogger().setLevel(logging.DEBUG)
logging.getLogger().addHandler(file_handler)
logging.getLogger().addHandler(console_handler)
