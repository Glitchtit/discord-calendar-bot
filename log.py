import gzip
import logging
import os
import shutil
import sys
import platform
import tempfile
from datetime import datetime
import atexit
from logging.handlers import TimedRotatingFileHandler, MemoryHandler
from logging.handlers import QueueHandler, QueueListener
import queue
from colorlog import ColoredFormatter
from environ import DEBUG, LOG_FORMAT

try:
    from pythonjsonlogger import jsonlogger
except ImportError:
    jsonlogger = None


class SizedTimedRotatingFileHandler(TimedRotatingFileHandler):
    """Rotates at midnight AND when the file exceeds *max_bytes*.

    Rotated files are gzip-compressed automatically (e.g. bot.log.2026-03-30.gz).
    """

    def __init__(self, filename, *, max_bytes: int = 0, **kwargs):
        super().__init__(filename, **kwargs)
        self.max_bytes = max_bytes
        self.namer = self._gzip_namer
        self.rotator = self._gzip_rotator

    def shouldRollover(self, record):
        if super().shouldRollover(record):
            return True
        if self.max_bytes > 0 and self.stream:
            self.stream.seek(0, 2)
            if self.stream.tell() + len(self.format(record)) >= self.max_bytes:
                return True
        return False

    @staticmethod
    def _gzip_namer(name: str) -> str:
        return name + ".gz"

    @staticmethod
    def _gzip_rotator(source: str, dest: str):
        with open(source, "rb") as f_in, gzip.open(dest, "wb") as f_out:
            shutil.copyfileobj(f_in, f_out)
        os.remove(source)

    def getFilesToDelete(self):
        """Override to locate .gz-compressed rotated files for cleanup."""
        dir_name, base_name = os.path.split(self.baseFilename)
        prefix = base_name + "."
        result = []
        for fn in os.listdir(dir_name):
            if not fn.startswith(prefix):
                continue
            # Strip .gz for date-suffix matching
            suffix = fn.removeprefix(prefix).removesuffix(".gz")
            if self.extMatch.match(suffix):
                result.append(os.path.join(dir_name, fn))
        if len(result) < self.backupCount:
            return []
        result.sort()
        return result[: len(result) - self.backupCount]

# ╔════════════════════════════════════════════════════════════════════╗
# ║ 📁 Log Directory & File Setup                                     ║
# ║ Creates the log directory if missing and defines log file path    ║
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
        except Exception as e:
            sys.stderr.write(f"log: cannot create {LOG_DIR}: {e}\n")
    
    # Try fallback locations
    for fallback in FALLBACK_DIRS:
        try:
            os.makedirs(fallback, exist_ok=True)
            test_file = os.path.join(fallback, "calendarbot.log")
            
            # Test if we can write to this directory
            if os.access(fallback, os.W_OK):
                active_log_file = test_file
                log_dir_used = fallback
                sys.stderr.write(f"log: using fallback log directory: {fallback}\n")
                return True
        except Exception:
            continue
    
    # Could not find any valid directory
    sys.stderr.write("WARNING: Could not find a writable log directory. Logging to file disabled.\n")
    return False

has_valid_log_dir = setup_log_directory()

# ╔════════════════════════════════════════════════════════════════════╗
# ║ 📋 Logger Initialization                                          ║
# ║ Sets up both console and file handlers with color and formatting  ║
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
        # File formatter: plain text or JSON depending on LOG_FORMAT env var
        if LOG_FORMAT == "json" and jsonlogger is not None:
            file_formatter = jsonlogger.JsonFormatter(
                "%(asctime)s %(levelname)s %(name)s %(filename)s %(lineno)d %(message)s",
                datefmt="%Y-%m-%dT%H:%M:%S",
                rename_fields={"asctime": "timestamp", "levelname": "level", "lineno": "line"},
            )
        else:
            if LOG_FORMAT == "json" and jsonlogger is None:
                sys.stderr.write("log: LOG_FORMAT=json but python-json-logger not installed, falling back to text\n")
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

        # File handler: logs everything to persistent storage with daily + size rotation
        if has_valid_log_dir:
            try:
                file_handler = SizedTimedRotatingFileHandler(
                    active_log_file,
                    when="midnight",
                    interval=1,
                    backupCount=7,
                    encoding="utf-8",
                    delay=False,
                    max_bytes=10 * 1024 * 1024,  # 10 MB
                )
                
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
                
                sys.stderr.write(f"log: logging to {active_log_file}\n")
            except Exception as e:
                sys.stderr.write(f"log: error setting up file handler: {e}\n")
        else:
            sys.stderr.write("log: file logging disabled (no writable directory)\n")

        # Console handler: outputs to stdout for quick feedback
        try:
            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setFormatter(console_formatter)
            console_handler.setLevel(logging.DEBUG if DEBUG else logging.INFO)
            handlers.append(console_handler)
        except Exception as e:
            sys.stderr.write(f"log: error setting up console handler: {e}\n")
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
                    
                sys.stderr.write("Logging shutdown complete.\n")
            except Exception as exc:
                sys.stderr.write(f"log: error during shutdown: {exc}\n")
                
        atexit.register(cleanup)
        
        # Log initial startup information
        logger.info(f"Logging initialized ({platform.platform()}) at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info(f"Log level: {'DEBUG' if DEBUG else 'INFO'}")
        if has_valid_log_dir:
            logger.info(f"Log directory: {log_dir_used}")
        else:
            logger.warning("File logging disabled - using console only")
            
    except Exception as e:
        sys.stderr.write(f"log: critical error initializing logger: {e}\n")
        # Fall back to basic logging
        basic_handler = logging.StreamHandler(sys.stdout)
        basic_formatter = logging.Formatter('%(levelname)s: %(message)s')
        basic_handler.setFormatter(basic_formatter)
        logger.addHandler(basic_handler)

# Add a convenience function for log file location
def get_log_file_location():
    return active_log_file if has_valid_log_dir else "Console only (no file)"
