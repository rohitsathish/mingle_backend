"""
Centralized configuration for Mingle Backend.

Combines all configuration settings including secrets, paths, and application settings.
"""

import os
from pathlib import Path
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import List, Optional
from dotenv import load_dotenv
from .logs import get_logger

# Load .env file if it exists (local development)
# In cloud deployment, this will be ignored and env vars will be used directly
# Use override=True to ensure .env values take precedence over conda environment variables
load_dotenv(override=True)

# Initialize logger
logger = get_logger(__name__)

# ============================================================================
# API Keys and Secrets
# ============================================================================

def get_openrouter_api_keys() -> List[str]:
    """Get OpenRouter API keys from environment variable (comma-separated)."""
    keys_raw = os.getenv("OPENROUTER_API_KEYS", "")
    if not keys_raw:
        logger.warning("No OpenRouter API keys configured.")
        return []
    
    keys = [key.strip() for key in keys_raw.split(",") if key.strip()]
    if not keys:
        logger.warning("OPENROUTER_API_KEYS is set but contains no valid keys.")
    
    return keys


def get_gemini_api_key() -> Optional[str]:
    """Get Google Gemini API key from environment."""
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        logger.warning("GEMINI_API_KEY not configured.")
    return key


def get_openai_api_key() -> Optional[str]:
    """Get OpenAI API key from environment."""
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        logger.warning("OPENAI_API_KEY not configured.")
    return key


def get_litellm_api_key() -> Optional[str]:
    """Get LiteLLM API key from environment."""
    key = os.getenv("LITELLM_API_KEY")
    if not key:
        logger.warning("LITELLM_API_KEY not configured.")
    return key


def get_google_places_api_key() -> Optional[str]:
    """Get Google Places API key from environment."""
    key = os.getenv("GOOGLE_PLACES_API_KEY")
    if not key:
        logger.warning("GOOGLE_PLACES_API_KEY not configured.")
    return key


def get_database_url() -> Optional[str]:
    """Get database connection URL."""
    return os.getenv("DATABASE_URL") or os.getenv("SUPABASE_URL")


def get_supabase_config() -> dict:
    """Get Supabase configuration."""
    return {
        "url": os.getenv("SUPABASE_URL"),
        "anon_key": os.getenv("SUPABASE_ANON_KEY"),
    }


def get_flaresolverr_url() -> str:
    """Get Flaresolverr service URL with fallback."""
    return os.getenv("FLARESOLVERR_URL", "http://localhost:8191/v1")


# ============================================================================
# Application Settings
# ============================================================================

# Environment detection
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
DEBUG = os.getenv("DEBUG", "false").lower() == "true"

# Project root directory
PROJECT_ROOT = Path(__file__).parent.parent

# ============================================================================
# File Paths
# ============================================================================

# Output directories - using exact .env variable names
MESSAGES_DIR = Path(os.getenv("MESSAGES_DIR", "./data/messages"))
CRAWLED_EVENTS_DIR = Path(os.getenv("CRAWLED_EVENTS_DIR", "./data/crawled_events"))
PARSED_EVENTS_DIR = Path(os.getenv("PARSED_EVENTS_DIR", "./data/parsed_events"))

# Import LOGS_DIR from logs.py to avoid circular dependency
from .logs import LOGS_DIR

# Ensure paths are absolute
MESSAGES_DIR = MESSAGES_DIR if MESSAGES_DIR.is_absolute() else PROJECT_ROOT / MESSAGES_DIR
CRAWLED_EVENTS_DIR = CRAWLED_EVENTS_DIR if CRAWLED_EVENTS_DIR.is_absolute() else PROJECT_ROOT / CRAWLED_EVENTS_DIR
PARSED_EVENTS_DIR = PARSED_EVENTS_DIR if PARSED_EVENTS_DIR.is_absolute() else PROJECT_ROOT / PARSED_EVENTS_DIR

# Browser profile directories
CHROME_PROFILE_DIR = Path(os.getenv("CHROME_PROFILE_DIR", str(PROJECT_ROOT / "chrome_profile")))
CRAWL4AI_PROFILE_DIR = Path(os.getenv("CRAWL4AI_PROFILE_DIR", str(PROJECT_ROOT / "chrome_profile_crawl4ai")))

# Ensure browser profile paths are absolute
CHROME_PROFILE_DIR = CHROME_PROFILE_DIR if CHROME_PROFILE_DIR.is_absolute() else PROJECT_ROOT / CHROME_PROFILE_DIR
CRAWL4AI_PROFILE_DIR = CRAWL4AI_PROFILE_DIR if CRAWL4AI_PROFILE_DIR.is_absolute() else PROJECT_ROOT / CRAWL4AI_PROFILE_DIR

# Dynamic file paths
def get_messages_json_path() -> str:
    """Generate timestamped messages JSON file path for scraper output."""
    timestamp = datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%Y%m%d_%H%M")
    return str(MESSAGES_DIR / f"messages_{timestamp}.json")

# Default messages JSON path (backwards compatibility)
MESSAGES_JSON_PATH = get_messages_json_path()

# ============================================================================
# Time Thresholds
# ============================================================================

# Number of days to look back for messages
DAYS_BACK_TO_PROCESS = int(os.getenv("DAYS_BACK_TO_PROCESS", "10"))

# ============================================================================
# API Configuration
# ============================================================================

# Service URLs
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# External services
FLARESOLVERR_CONFIG = {
    "url": get_flaresolverr_url(),
    "timeout": int(os.getenv("FLARESOLVERR_TIMEOUT", "300")),
}

# ============================================================================
# Browser Configuration
# ============================================================================

# Browser settings
BROWSER_HEADLESS = os.getenv("BROWSER_HEADLESS", "false").lower() == "true"
CHROME_DEBUGGING_PORT = int(os.getenv("CHROME_DEBUGGING_PORT", "9222"))

BROWSER_CONFIG = {
    "headless": BROWSER_HEADLESS,
    "debugging_port": CHROME_DEBUGGING_PORT,
    "profile_dir": CHROME_PROFILE_DIR,
}

# ============================================================================
# Flaresolverr Configuration
# ============================================================================

ACTIVATE_FLARESOLVERR = os.getenv("ACTIVATE_FLARESOLVERR", "true").lower() == "true"
FLARESOLVERR_DO_AUTH = os.getenv("FLARESOLVER_DO_AUTH", "false").lower() == "true"
FLARESOLVERR_USERNAME = os.getenv("FLARESOLVER_USERNAME", "")
FLARESOLVERR_PASSWORD = os.getenv("FLARESOLVER_PASSWORD", "")

# ============================================================================
# Database Configuration
# ============================================================================

DATABASE_CONFIG = {
    "url": get_database_url(),
    "pool_size": int(os.getenv("DB_POOL_SIZE", "5")),
    "timeout": int(os.getenv("DB_TIMEOUT", "30")),
}

# ============================================================================
# Cache Configuration
# ============================================================================

# Cache directory configuration
CACHE_DIR = Path(os.getenv("CACHE_DIR", str(PROJECT_ROOT / "data" / "cache")))
CACHE_DIR = CACHE_DIR if CACHE_DIR.is_absolute() else PROJECT_ROOT / CACHE_DIR

CACHE_CONFIG = {
    "dir": CACHE_DIR,
    "default_expiry": int(os.getenv("CACHE_EXPIRY_HOURS", "24")) * 3600,  # Convert to seconds
    "max_size": int(os.getenv("CACHE_MAX_SIZE_MB", "250")) * 1024 * 1024,  # Convert to bytes (250MB default)
}

# ============================================================================
# Retry and Error Handling
# ============================================================================

RETRY_CONFIG = {
    "max_retries_per_model": int(os.getenv("MAX_RETRIES_PER_MODEL", "2")),
    "max_backoff": int(os.getenv("MAX_BACKOFF_SECONDS", "60")),
    "base_backoff": int(os.getenv("BASE_BACKOFF_SECONDS", "1")),
}



# ============================================================================
# Validation
# ============================================================================

def validate_config() -> bool:
    """Validate configuration settings."""

    # Create required directories
    required_dirs = [
        MESSAGES_DIR, CRAWLED_EVENTS_DIR, PARSED_EVENTS_DIR, LOGS_DIR,
        CACHE_CONFIG["dir"], CHROME_PROFILE_DIR, CRAWL4AI_PROFILE_DIR
    ]
    
    for dir_path in required_dirs:
        try:
            dir_path.mkdir(parents=True, exist_ok=True)
        except (OSError, PermissionError) as e:
            logger.error(f"Failed to create directory {dir_path}: {e}")
            raise RuntimeError(f"Configuration validation failed: {e}")

    # Validate critical paths exist after creation
    critical_paths = [
        MESSAGES_DIR, CRAWLED_EVENTS_DIR, PARSED_EVENTS_DIR, LOGS_DIR, CACHE_CONFIG["dir"]
    ]
    
    for path in critical_paths:
        if not path.exists():
            logger.error(f"Required directory does not exist: {path}")
            raise RuntimeError(f"Configuration validation failed: Required directory does not exist: {path}")
        if not os.access(path, os.W_OK):
            logger.error(f"Directory is not writable: {path}")
            raise RuntimeError(f"Configuration validation failed: Directory is not writable: {path}")

    logger.info("Configuration validation completed successfully!")
    return True


# ============================================================================
# Configuration Initialization (singleton pattern)
# ============================================================================

def _initialize_config():
    """Initialize all configuration values and validate setup."""
    global OPENROUTER_API_KEYS, GEMINI_API_KEY, OPENAI_API_KEY, LITELLM_API_KEY
    global GOOGLE_PLACES_API_KEY, DATABASE_URL, SUPABASE_CONFIG, FLARESOLVERR_URL
    global CONFIG_VALID
    
    # Load API Keys
    OPENROUTER_API_KEYS = get_openrouter_api_keys()
    GEMINI_API_KEY = get_gemini_api_key()
    OPENAI_API_KEY = get_openai_api_key()
    LITELLM_API_KEY = get_litellm_api_key()
    GOOGLE_PLACES_API_KEY = get_google_places_api_key()
    
    # Load Database Configuration
    DATABASE_URL = get_database_url()
    SUPABASE_CONFIG = get_supabase_config()
    
    # Load Service URLs
    FLARESOLVERR_URL = get_flaresolverr_url()
    
    # Validate configuration
    CONFIG_VALID = validate_config()
    
    logger.info("Configuration initialized successfully.")

# Initialize configuration on import
_initialize_config()