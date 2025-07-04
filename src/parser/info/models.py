"""
LLM model configurations for Mingle Backend.

Defines available LLM models and their configurations for different providers.
"""

import os
from typing import Dict, Any, List
from datetime import datetime

from aiolimiter import AsyncLimiter

# ============================================================================
# LLM Model Configurations
# ============================================================================

MODELS: Dict[str, Dict[str, Any]] = {
    # OpenAI Models
    "gpt-4.1-nano": {  # Unsuitable for html parsing, misses details. Keeping for image analysis
        "name": "gpt-4.1-nano",
        "input_tokens": 1e6,
        "route": "openai",
        "tool_mode": "tools",
        "rate": (10, 1),  # 10 calls per second
    },
    "gpt-4.1-mini": {  # Unsuitable for html parsing.
        "name": "gpt-4.1-mini",
        "input_tokens": 1e6,
        "route": "openai",
        "tool_mode": "tools",
        "rate": (10, 1),  # 10 calls per second
    },
    "gpt-4o-mini": {  # Unsuitable for html parsing
        "name": "gpt-4o-mini",
        "input_tokens": 128e3,
        "route": "openai",
        "tool_mode": "tools",
        "rate": (10, 1),  # 10 calls per second
    },
    "o4-mini-low": {
        "name": "o4-mini",
        "input_tokens": 128e3,
        "route": "openai",
        "tool_mode": "tools",
        "reasoning": "low",
        "rate": (10, 1),  # 10 calls per second
    },
    "o4-mini-medium": {
        "name": "o4-mini",
        "input_tokens": 128e3,
        "route": "openai",
        "tool_mode": "tools",
        "reasoning": "medium",
        "rate": (10, 1),  # 10 calls per second
    },  
    "o4-mini-high": {
        "name": "o4-mini",
        "input_tokens": 128e3,
        "route": "openai",
        "tool_mode": "tools",
        "reasoning": "high",
        "rate": (10, 1),  # 10 calls per second
    },
    # OpenRouter Models
    "gemini-2.5-pro": {
        "name": "google/gemini-2.5-pro-preview",
        "input_tokens": 1e6,
        "route": "openrouter",
        "tool_mode": "tools",
        "rate": (2, 1),
    },
    # "o4-mini-high": {
    #     "name": "openai/o4-mini-high",
    #     "input_tokens": 2e5,
    #     "route": "openrouter",
    #     "tool_mode": "tools",
    #     "rate": (2, 1),
    # },
    # "gemini-2-flash": {
    #     "name": "google/gemini-2.0-flash-exp:free",
    #     "input_tokens": 1e6,
    #     "route": "openrouter",
    #     "rate": (2, 1),
    # },
    "grok-3-mini": {
        "name": "x-ai/grok-3-mini-beta",
        "input_tokens": 1.3e5,
        "route": "openrouter",
        "rate": (2, 1),
    },
    # OpenRouter Models (Free)
    "qwq-32b": {
        "name": "qwen/qwq-32b:free",
        "input_tokens": 4e4,
        "route": "openrouter",
        "rate": (2, 1),
    },
    "deepseek-r1": {
        "name": "deepseek/deepseek-r1:free",
        "input_tokens": 1.64e5,
        "route": "openrouter",
        "rate": (2, 1),
    },
    "llama-4-maverick": {
        "name": "meta-llama/llama-4-maverick:free",
        "input_tokens": 256e3,
        "route": "openrouter",
        "rate": (2, 1),
    },
    "llama-4-scout": {
        "name": "meta-llama/llama-4-scout:free",
        "input_tokens": 64e3,
        "route": "openrouter",
        "rate": (1, 3.5),
    },
    "mistral-small-3.2": {
        "name": "mistralai/mistral-small-3.2-24b-instruct:free",
        "input_tokens": 96e3,
        "route": "openrouter",
        "rate": (2, 1),
    },
    # Gemini Models (Direct API)
    "gemini-2.5-flash-google": {
        "name": "gemini-2.5-flash-preview-05-20",
        "input_tokens": 1e6,
        "route": "gemini",
        "tool_mode": "gemini_json",
        "rate": (1, 2),
    },
    "gemini-2-flash-google": {
        "name": "gemini-2.0-flash",
        "route": "gemini",
        "rate": (1, 4.5),
        "tool_mode": "gemini_json",
    },
    "gemini-2-flash-lite-google": {
        "name": "gemini-2.0-flash-lite",
        "route": "gemini",
        "rate": (1, 2.5),
        "tool_mode": "gemini_json",
    },
    # Chutes Models
    "minimax-m1-chutes": {
        "name": "openai/MiniMaxAI/MiniMax-M1-80k",
        "input_tokens": 256e3,
        "route": "chutes",
        "rate": (1, 4),
    },
    "qwen3-235b-chutes": {
        "name": "openai/Qwen/Qwen3-235B-A22B",
        "input_tokens": 1e6,
        "route": "chutes",
        "rate": (1, 4),
    },
    "deepseek-r1-chutes": {
        "name": "openai/deepseek-ai/DeepSeek-R1",
        "input_tokens": 1.64e5,
        "route": "chutes",
        "rate": (1, 4),
    },
    "deepseek-r1-0528-chutes": {
        "name": "openai/deepseek-ai/DeepSeek-R1-0528",
        "input_tokens": 1.64e5,
        "route": "chutes",
        "rate": (1, 4),
    },
    "mai-r1-chutes": {
        "name": "openai/microsoft/MAI-DS-R1-FP8",
        "input_tokens": 1e6,
        "route": "chutes",
        "rate": (1, 4),
    },
    # Copilot API Models
    "gemini-2.5-pro-copilot": {
        "name": "openai/gemini-2.5-pro",
        "input_tokens": 1e6,
        "route": "copilot",
        "tool_mode": "json",
        "rate": (8, 1),
    },
    "o4-mini-copilot": {
        "name": "openai/o4-mini",
        "input_tokens": 2e5,
        "route": "copilot",
        "tool_mode": "tools",
        "rate": (8, 1),
    },
    "sonnet-3.7-thinking-copilot": { #Was unable to split events that o4-minihigh, gemini-2.5-flash and gemini-2.5-pro could
        "name": "openai/claude-3.7-sonnet-thought",
        "input_tokens": 1e5,
        "route": "copilot",
        "tool_mode": "json",
        "rate": (8, 1),
    },
    "gpt-4.1-copilot": {
        "name": "openai/gpt-4.1",
        "input_tokens": 1e6,
        "route": "copilot",
        "tool_mode": "tools",
        "rate": (8, 1),
    },
    "gpt-4o-copilot": {
        "name": "openai/gpt-4o",
        "input_tokens": 128e3,
        "route": "copilot",
        "tool_mode": "tools",
        "rate": (8, 1),
    },
}

# ============================================================================
# Configuration Constants
# ============================================================================

# Working file suffix for incremental processing
WORKING_FILE_SUFFIX = "_working"

# API and Retry Configuration
MAX_RETRIES_PER_MODEL = 2
MAX_BACKOFF = 60  # 1 minute in seconds
BASE_BACKOFF = 1  # Start with 1 second

# URL cache for storing fetched content
URL_CACHE = {}

# ============================================================================
# Utility Functions
# ============================================================================

def get_model_config(model_key: str) -> Dict[str, Any]:
    """Get configuration for a specific model."""
    if model_key not in MODELS:
        raise KeyError(f"Model '{model_key}' not found. Available models: {list(MODELS.keys())}")
    return MODELS[model_key]

def get_models_by_route(route: str) -> Dict[str, Dict[str, Any]]:
    """Get all models for a specific route/provider."""
    return {key: config for key, config in MODELS.items() if config.get("route") == route}

def get_available_routes() -> List[str]:
    """Get list of all available routes/providers."""
    routes = set()
    for config in MODELS.values():
        if "route" in config:
            routes.add(config["route"])
    return sorted(list(routes))

def get_model_name(model_key: str) -> str:
    """Get the actual model name for API calls."""
    config = get_model_config(model_key)
    return config.get("name", model_key)

def get_models_with_tool_support() -> Dict[str, Dict[str, Any]]:
    """Get models that support tool mode."""
    return {key: config for key, config in MODELS.items() if "tool_mode" in config}

# ============================================================================
# Model Selection for Tasks
# ============================================================================

def get_model_for_task(task: str) -> str:
    """Get model for specific task from environment variable (required)."""
    env_key = f"MODEL_{task.upper()}"
    env_model = os.getenv(env_key)
    
    if not env_model:
        raise ValueError(
            f"Environment variable '{env_key}' is required but not set. "
            f"Available models: {list(MODELS.keys())}"
        )
    
    if env_model not in MODELS:
        raise ValueError(
            f"Model '{env_model}' from environment variable '{env_key}' not found in MODELS. "
            f"Available models: {list(MODELS.keys())}"
        )
    
    return env_model

def get_models_for_event_extraction() -> List[str]:
    """Get models for event extraction from environment variable (required)."""
    env_models = os.getenv("EVENT_EXTRACTION_MODELS")
    
    if not env_models:
        raise ValueError(
            "Environment variable 'EVENT_EXTRACTION_MODELS' is required but not set. "
            f"Available models: {list(MODELS.keys())}"
        )
    
    # Parse comma-separated model keys from environment
    model_keys = [key.strip() for key in env_models.split(",")]
    
    # Validate all models exist - raise error for any invalid models
    invalid_models = [key for key in model_keys if key not in MODELS]
    if invalid_models:
        raise ValueError(
            f"Invalid model(s) in EVENT_EXTRACTION_MODELS: {invalid_models}. "
            f"Available models: {list(MODELS.keys())}"
        )
    
    # Return all valid models
    return model_keys


# ============================================================================
# Rate Limiting
# ============================================================================

# Setup logging
# Use centralized logging
from config.logs import get_logger
logger = get_logger(__name__)

# Per-model rate limiters cache
_model_limiters: Dict[str, AsyncLimiter] = {}

def get_model_limiter(model_key: str) -> AsyncLimiter:
    """Get or create a rate limiter for a specific model."""
    if model_key not in _model_limiters:
        try:
            model_config = get_model_config(model_key)
            rate = model_config.get("rate", (1, 3))  # Default: 1 call per 3 seconds
            calls, period = rate
            _model_limiters[model_key] = AsyncLimiter(calls, period)
            logger.info(f"Created rate limiter for {model_key}: {calls} calls per {period}s")
        except KeyError:
            # Fallback for unknown models
            _model_limiters[model_key] = AsyncLimiter(1, 3)
            logger.warning(f"Using default rate limiter for unknown model {model_key}")
    
    return _model_limiters[model_key]
