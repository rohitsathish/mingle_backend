"""Centralized logging configuration for Mingle Backend."""

import logging
import logging.handlers
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

# Global flag to track if logging has been initialized
_logging_initialized = False
_shared_handlers = []

# ============================================================================
# Logging Configuration
# ============================================================================

# Load environment variables directly (to avoid circular imports)
import os
from dotenv import load_dotenv

# Load .env file to access environment variables
load_dotenv(override=True)

# Load logging configuration from environment (after loading .env)
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOGS_DIR_STR = os.getenv("LOGS_DIR", "./data/logs")
LOG_MAX_SIZE_MB = int(os.getenv("LOG_MAX_SIZE_MB", "50"))
LOG_BACKUP_COUNT = int(os.getenv("LOG_BACKUP_COUNT", "5"))

# Set up paths
PROJECT_ROOT = Path(__file__).parent.parent
LOGS_DIR = Path(LOGS_DIR_STR)
LOGS_DIR = LOGS_DIR if LOGS_DIR.is_absolute() else PROJECT_ROOT / LOGS_DIR

# Ensure logs directory exists
LOGS_DIR.mkdir(parents=True, exist_ok=True)

LOGGING_CONFIG = {
    "dir": LOGS_DIR,
    "level": LOG_LEVEL,
    "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    "max_size_mb": LOG_MAX_SIZE_MB,
    "backup_count": LOG_BACKUP_COUNT,
}

def initialize_logging():
    """Initialize global logging configuration once."""
    global _logging_initialized, _shared_handlers
    
    if _logging_initialized:
        return
    
    # Fix Unicode encoding issues on Windows
    if os.name == "nt":  # Windows
        os.environ["PYTHONIOENCODING"] = "utf-8"
        os.environ["PYTHONUTF8"] = "1"
        # Set console code page to UTF-8 if possible
        try:
            import subprocess
            subprocess.run(["chcp", "65001"], shell=True, capture_output=True)
        except Exception:
            pass  # Ignore if chcp fails
    
    # Create shared formatter
    formatter = logging.Formatter(
        LOGGING_CONFIG["format"],
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    
    # Console handler with UTF-8 support
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    
    # Ensure UTF-8 encoding on Windows
    if hasattr(console_handler.stream, 'reconfigure'):
        try:
            console_handler.stream.reconfigure(encoding='utf-8')
        except Exception:
            pass
    
    # Single unified log file (persistent across runs)
    log_file = LOGGING_CONFIG["dir"] / "mingle_backend.log"
    
    # Create rotating file handler (appends to existing file)
    file_handler = logging.handlers.RotatingFileHandler(
        log_file,
        maxBytes=LOGGING_CONFIG["max_size_mb"] * 1024 * 1024,
        backupCount=LOGGING_CONFIG["backup_count"],
        encoding="utf-8"  # Explicit UTF-8 encoding for files
    )
    
    # Add session separator for new runs
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    session_separator = f"\n{'='*80}\nSESSION START: {timestamp}\n{'='*80}\n"
    
    # Write session separator directly to log file if it exists
    try:
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(session_separator)
    except Exception:
        pass  # Ignore if file doesn't exist yet
    file_handler.setFormatter(formatter)
    
    # Store shared handlers
    _shared_handlers = [console_handler, file_handler]
    
    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, LOGGING_CONFIG["level"]))
    
    # Clear any existing handlers
    root_logger.handlers.clear()
    
    # Add shared handlers to root logger
    for handler in _shared_handlers:
        root_logger.addHandler(handler)
    
    # Configure third-party loggers
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)
    
    # Configure crawl4ai logger to use our handlers
    crawl4ai_logger = logging.getLogger("crawl4ai")
    crawl4ai_logger.setLevel(logging.INFO)
    crawl4ai_logger.handlers.clear()
    for handler in _shared_handlers:
        crawl4ai_logger.addHandler(handler)
    crawl4ai_logger.propagate = False  # Prevent duplicate logs
    
    _logging_initialized = True


def get_logger(name: Optional[str] = None) -> logging.Logger:
    """Get a logger instance with centralized configuration.
    
    Args:
        name: Logger name (should be __name__ from calling module)
        
    Returns:
        Configured logger instance
    """
    # Initialize logging if not already done
    initialize_logging()
    
    # Get logger with proper name
    logger_name = name if name else __name__
    logger = logging.getLogger(logger_name)
    
    # Don't add handlers to individual loggers - they inherit from root
    # This ensures all logs go to the same unified file
    
    return logger


# Initialize logging early
initialize_logging()
