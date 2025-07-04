"""Core LLM API functionality.

Provides instructor chat completion and Crawl4AI integration
for processing messages and extracting event information.
"""

import asyncio
import hashlib
import json
import logging
import os
import re
import time
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional, Set, Tuple, Type, TypeVar, Union
from urllib.parse import quote_plus, unquote

import diskcache
import google.generativeai as genai
import httpx
import instructor
import litellm
import tenacity
from aiolimiter import AsyncLimiter
from config.config import OPENROUTER_URL, CACHE_CONFIG
from src.parser.info.models import get_model_config, get_model_limiter
from config.config import OPENROUTER_API_KEYS, GEMINI_API_KEY, get_openai_api_key
from openai import AsyncOpenAI
from openai import RateLimitError as OpenAIRateLimitError
from openai._exceptions import APIStatusError
from pydantic import BaseModel, Field
from tenacity import (
    RetryCallState,
    before_sleep_log,
    retry,
    retry_if_exception,
    stop_after_attempt,
)
from litellm import acompletion
from copy import deepcopy

if os.name == "nt":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

litellm._logging._disable_debugging()

# Setup logging using centralized config
from config.logs import get_logger
logger = get_logger(__name__)


# Configure Gemini with centralized config
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

# HTTPX Client setup
TIMEOUT_CONFIG = httpx.Timeout(10.0, read=180.0)
HTTPX_CLIENT = httpx.AsyncClient(timeout=TIMEOUT_CONFIG)

# Diskcache setup for persistent caching with size limit
cache = diskcache.Cache(
    directory=str(CACHE_CONFIG["dir"]),
    size_limit=CACHE_CONFIG["max_size"]  # 250MB default
)

# Type variable for Pydantic models
T = TypeVar("T", bound=BaseModel)


async def close_httpx_client():
    """Close the shared HTTPX client."""
    await HTTPX_CLIENT.aclose()


def clear_cache():
    """Clear all entries from the diskcache."""
    try:
        count_before = len(cache)
        cache.clear()
        logger.info(f"Cache cleared successfully. Removed {count_before} entries.")
        return True
    except Exception as e:
        logger.error(f"Error clearing cache: {str(e)}")
        return False


def parse_data_uri(uri: str) -> Optional[Tuple[str, str]]:
    """Parse a data URI into mime type and base64 data."""
    match = re.match(r"data:(?P<mime_type>[^;]+);base64,(?P<data>.*)", uri)
    if match:
        return match.group("mime_type"), match.group("data")
    logger.warning(f"Could not parse data URI: {uri[:50]}...")
    return None


def extract_retry_seconds(exc: Exception) -> Optional[float]:
    """Extract retry delay in seconds from rate limit errors.

    Prioritizes finding RetryInfo in the raw error data from Google AI Studio.
    """
    # Extract error dict from different error types
    error_dict = None

    # Check for dictionary in InstructorRetryException
    if (
        hasattr(exc, "__class__")
        and exc.__class__.__name__ == "InstructorRetryException"
    ):
        if hasattr(exc, "args") and exc.args and isinstance(exc.args[0], dict):
            error_dict = exc.args[0]
            logger.info(f"Found dictionary in InstructorRetryException")

    # Check for dictionary in ValueError
    elif isinstance(exc, ValueError):
        if hasattr(exc, "args") and exc.args and isinstance(exc.args[0], dict):
            error_dict = exc.args[0]
            logger.info(f"Found dictionary in ValueError")

    # Standard OpenAI RateLimitError
    elif isinstance(exc, OpenAIRateLimitError) and exc.status_code == 429:
        error_dict = exc.body if hasattr(exc, "body") else None
        logger.info(f"Found OpenAIRateLimitError with status 429")

    # Generic exceptions with dict in args
    elif hasattr(exc, "args") and exc.args and isinstance(exc.args[0], dict):
        error_dict = exc.args[0]
        logger.info(f"Found dictionary in generic exception args")

    # No valid error dictionary found
    if not error_dict:
        logger.warning(f"No error dictionary found in exception: {type(exc).__name__}")
        return None

    try:
        # Method 1: Extract RetryInfo from 'raw' metadata (Google AI Studio format)
        if "metadata" in error_dict and "raw" in error_dict["metadata"]:
            raw_str = error_dict["metadata"]["raw"]
            logger.info(f"Found raw metadata, looking for RetryInfo")

            # First attempt: direct regex on the raw string (most reliable)
            retry_info_match = re.search(
                r'"@type":\s*"[^"]*RetryInfo"[^}]*"retryDelay":\s*"(\d+)s"', raw_str
            )
            if retry_info_match:
                retry_seconds = float(retry_info_match.group(1))
                logger.info(f"Extracted RetryInfo delay via regex: {retry_seconds}s")
                return retry_seconds

            # Second attempt: full JSON parsing
            try:
                raw_data = json.loads(raw_str)
                if "error" in raw_data and "details" in raw_data["error"]:
                    for detail in raw_data["error"]["details"]:
                        if (
                            isinstance(detail, dict)
                            and "@type" in detail
                            and "RetryInfo" in detail["@type"]
                        ):
                            if "retryDelay" in detail:
                                delay_str = detail["retryDelay"]
                                match = re.match(r"(\d+(\.\d+)?)s", delay_str)
                                if match:
                                    retry_seconds = float(match.group(1))
                                    logger.info(
                                        f"Extracted RetryInfo delay via JSON parsing: {retry_seconds}s"
                                    )
                                    return retry_seconds
            except json.JSONDecodeError:
                logger.warning("Failed to parse 'raw' metadata as JSON")

        # Method 2: Check for rate limit headers
        if "metadata" in error_dict and "headers" in error_dict["metadata"]:
            headers = error_dict["metadata"]["headers"]
            if isinstance(headers, dict):
                # Check for Retry-After header
                if "retry-after" in headers:
                    try:
                        retry_seconds = float(headers["retry-after"])
                        logger.info(f"Extracted Retry-After header: {retry_seconds}s")
                        return retry_seconds
                    except ValueError:
                        logger.warning(
                            f"Invalid Retry-After value: {headers['retry-after']}"
                        )

                # If X-RateLimit-Reset is present, trigger key rotation instead of waiting
                if "X-RateLimit-Reset" in headers:
                    logger.info(
                        "Found X-RateLimit-Reset header, using key rotation strategy"
                    )
                    return None

        logger.info("No retry delay information found, using key rotation strategy")
        return None

    except Exception as e:
        logger.error(f"Error while extracting retry delay: {e}")
        return None


def is_rate_limit_error(exc: Exception) -> bool:
    """Check if the exception is a rate limit error.

    Handles multiple rate limit error formats from OpenRouter and providers.
    """
    # Check for InstructorRetryException by name
    if (
        hasattr(exc, "__class__")
        and exc.__class__.__name__ == "InstructorRetryException"
    ):
        try:
            # Extract the error dictionary
            if hasattr(exc, "args") and exc.args:
                error_dict = exc.args[0]
                if isinstance(error_dict, dict) and error_dict.get("code") == 429:
                    provider = ""
                    if (
                        "metadata" in error_dict
                        and "provider_name" in error_dict["metadata"]
                    ):
                        provider = f" from {error_dict['metadata']['provider_name']}"
                    logger.warning(
                        f"Detected InstructorRetryException with Rate Limit{provider}: {error_dict.get('message', 'Rate limit exceeded')}"
                    )
                    return True
        except Exception as e:
            logger.debug(f"Error parsing InstructorRetryException: {e}")

    # Standard OpenAI RateLimitError
    if isinstance(exc, OpenAIRateLimitError) and exc.status_code == 429:
        logger.warning(f"Detected OpenAI Rate Limit Error: {exc}")
        return True

    # ValueError with rate limit dictionary
    if isinstance(exc, ValueError):
        try:
            if hasattr(exc, "args") and exc.args and isinstance(exc.args[0], dict):
                error_dict = exc.args[0]
                if error_dict.get("code") == 429:
                    provider = ""
                    if (
                        "metadata" in error_dict
                        and "provider_name" in error_dict["metadata"]
                    ):
                        provider = f" from {error_dict['metadata']['provider_name']}"
                    logger.warning(
                        f"Detected ValueError Rate Limit Error{provider}: {error_dict.get('message', 'Rate limit exceeded')}"
                    )
                    return True
        except Exception as e:
            logger.debug(f"Error parsing ValueError for rate limit: {e}")

    # Generic exception with rate limit info in string format
    if hasattr(exc, "__str__"):
        error_str = str(exc)
        if "429" in error_str and (
            "rate limit" in error_str.lower()
            or "provider returned error" in error_str.lower()
        ):
            logger.warning(
                f"Detected rate limit in exception string: {error_str[:100]}..."
            )
            return True

    return False


def custom_wait(retry_state: RetryCallState) -> float:
    """Determine wait time based on the exception.

    Uses extract_retry_seconds to find a specific delay.
    If no specific delay, returns a minimal wait time for key rotation.
    """
    exc = retry_state.outcome.exception()
    if exc:
        delay = extract_retry_seconds(exc)
        if delay is not None:
            logger.info(f"Applying specific delay of {delay:.2f} seconds.")
            return delay

    # If no specific delay found, return a very short delay to allow the next attempt
    logger.info("Applying minimal delay for next attempt (likely key rotation).")
    return 2


def is_server_error(exc: Exception) -> bool:
    """Check if the exception is a server error (HTTP 500)."""
    # Check for InstructorRetryException or ValueError with code 500
    if (
        hasattr(exc, "__class__")
        and exc.__class__.__name__ == "InstructorRetryException"
    ) or isinstance(exc, ValueError):
        try:
            if hasattr(exc, "args") and exc.args and isinstance(exc.args[0], dict):
                error_dict = exc.args[0]
                if error_dict.get("code") == 500:
                    provider = ""
                    if (
                        "metadata" in error_dict
                        and "provider_name" in error_dict["metadata"]
                    ):
                        provider = f" from {error_dict['metadata']['provider_name']}"
                    logger.warning(
                        f"Detected server error {provider}: {error_dict.get('message', 'Internal Server Error')}"
                    )
                    return True
        except Exception as e:
            logger.debug(f"Error parsing exception for server error: {e}")

    # Check for standard HTTP errors
    if (
        isinstance(exc, (httpx.HTTPStatusError, APIStatusError))
        and getattr(exc, "status_code", 0) == 500
    ):
        logger.warning(f"Detected HTTP 500 error: {exc}")
        return True

    # Generic exception with error info in string format
    if hasattr(exc, "__str__"):
        error_str = str(exc)
        if (
            "500" in error_str or "Internal Server Error" in error_str
        ) and "code" in error_str:
            logger.warning(
                f"Detected 500 error in exception string: {error_str[:100]}..."
            )
            return True

    return False


async def instructor_chat_completion(
    model: str,
    response_model: Union[Type[T], List[Type[T]]],
    content: str,
    image_urls: Optional[List[str]] = None,
    system_prompt: Optional[str] = None,
    tool_mode: Optional[str] = "tools",
    require_params: bool = False,
    max_retries: int = 5,
    route: Literal["openrouter", "openai", "gemini", "chutes", "copilot"] = "openrouter",
    reasoning: Optional[Literal["low", "medium", "high"]] = False,
    model_key: Optional[str] = None,
) -> T:
    """Instructor chat completion with robust retry handling and caching.

    Automatically handles rate limiting with appropriate retries and includes
    explicit rate limiting via aiolimiter.
    """
    # tool_mode dict
    tool_mode_dict = {
        "tools": instructor.Mode.TOOLS,
        "json": instructor.Mode.JSON,
        "md_json": instructor.Mode.MD_JSON,
        "json_schema": instructor.Mode.JSON_SCHEMA,
        "gemini_json": instructor.Mode.GEMINI_JSON,
        "gemini_tools": instructor.Mode.GEMINI_TOOLS,
        "anthropic_tools": instructor.Mode.ANTHROPIC_TOOLS,
    }

    # Shared state across retries
    current_key_index = 0
    keys_tried_in_current_attempt: Set[int] = set()
    total_keys = len(OPENROUTER_API_KEYS) if OPENROUTER_API_KEYS else 0

    if total_keys == 0 and route == "openrouter":
        logger.error(
            "No OpenRouter API keys available, cannot proceed with OpenRouter route."
        )
        raise ValueError("OpenRouter API keys are not configured or empty.")

    # Provider-specific options
    # if route in ["openrouter", "openai"] and reasoning:
    #     extra_body = {"reasoning": reasoning} 
    
    # Only cache image-based calls (not event extraction)
    should_cache = (
        bool(image_urls)
        and len(image_urls) == 1
        and image_urls[0].startswith("data:image")
    )
    if should_cache:
        img_hash = hashlib.sha256(image_urls[0].encode("utf-8")).hexdigest()
        cache_key = f"llm:img:{model}:{tool_mode}:{content[:40]}:{img_hash}"
        cached = cache.get(cache_key)
        if cached is not None:
            logger.info(f"[CACHE HIT] Image API for model {model}")
            # Parse from JSON string to Pydantic model
            if isinstance(response_model, type) and hasattr(
                response_model, "parse_raw"
            ):
                return response_model.parse_raw(cached)
            elif isinstance(response_model, list) and hasattr(
                response_model[0], "parse_obj"
            ):
                return parse_obj_as(List[response_model[0]], json.loads(cached))
            else:
                return cached

    @retry(
        retry=retry_if_exception(
            lambda exc: is_rate_limit_error(exc) or is_server_error(exc)
        ),
        wait=custom_wait,
        stop=stop_after_attempt(
            (max_retries * total_keys + 1) if total_keys > 0 else max_retries + 1
        ),
        before_sleep=before_sleep_log(logger, logging.INFO),
        reraise=True,
    )
    async def _execute_with_retry():
        nonlocal current_key_index, keys_tried_in_current_attempt
        nonlocal model

        # Ensure we have keys if using OpenRouter
        if route == "openrouter" and total_keys == 0:
            raise ValueError("OpenRouter API keys are not configured or empty.")

        # Check if we've exhausted all keys in this attempt cycle
        if route == "openrouter" and len(keys_tried_in_current_attempt) >= total_keys:
            logger.error(
                "All OpenRouter API keys have been tried and failed within retry attempts. Raising."
            )
            raise tenacity.TryAgain(
                "Exhausted all OpenRouter API keys during retry attempts."
            )

        # Get current API key for this attempt
        api_key = None
        if route == "openrouter":
            api_key = OPENROUTER_API_KEYS[current_key_index]
            keys_tried_in_current_attempt.add(current_key_index)
        elif route == "openai":
            api_key = get_openai_api_key()
            if not api_key:
                logger.error("OPENAI_API_KEY environment variable not set.")
                raise ValueError("OPENAI_API_KEY is not configured.")
        elif route == "gemini":
            api_key = os.getenv("GEMINI_API_KEY")
            if not api_key:
                logger.error("GEMINI_API_KEY environment variable not set.")
                raise ValueError("GEMINI_API_KEY is not configured.")
        elif route == "chutes" or route == "copilot":
            api_key = os.getenv("LITELLM_API_KEY")
            if not api_key:
                logger.error(
                    "LITELLM_API_KEY environment variable not set and no fallback key available."
                )
                raise ValueError("LITELLM_API_KEY is not configured.")

        # Create client and prepare messages based on route
        client = None
        messages = []

        if route == "openrouter":
            # --- OpenRouter Route ---
            openai_client = AsyncOpenAI(
                base_url="https://openrouter.ai/api/v1",
                api_key=api_key,
                max_retries=0,
                # http_client=HTTPX_CLIENT,
            )
            # Use instructor.from_openai for OpenRouter (OpenAI-compatible API)
            client = instructor.from_openai(
                openai_client, 
                mode=tool_mode_dict.get(tool_mode)
            )
            # Build messages for OpenRouter (reset messages for this route)
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            user_content_parts = [{"type": "text", "text": content}]
            if image_urls:
                user_content_parts.extend(
                    {"type": "image_url", "image_url": {"url": url}}
                    for url in image_urls
                )
            messages.append({"role": "user", "content": user_content_parts})

        elif route == "openai":
            # --- OpenAI Route ---
            openai_client = AsyncOpenAI(
                api_key=api_key,
                max_retries=0,
                http_client=HTTPX_CLIENT,
            )
            # Use instructor.from_openai for OpenAI with explicit mode
            client = instructor.from_openai(
                openai_client, 
                mode=tool_mode_dict.get(tool_mode)
            )
            # Build messages for OpenAI
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            user_content_parts = [{"type": "text", "text": content}]
            if image_urls:
                user_content_parts.extend(
                    {"type": "image_url", "image_url": {"url": url}}
                    for url in image_urls
                )
            messages.append({"role": "user", "content": user_content_parts})

        elif route == "gemini":
            # --- Gemini Route ---
            genai_model = genai.GenerativeModel(model_name=f"models/{model}")
            client = instructor.from_gemini(
                client=genai_model,
                mode=tool_mode_dict.get(tool_mode),
                use_async=True,
            )

            # Build messages/contents for Gemini (reset messages for Gemini)
            messages = []
            effective_content = (
                f"{system_prompt}\\n\\n{content}" if system_prompt else content
            )
            gemini_user_parts = [{"text": effective_content}]

            if image_urls:
                for url in image_urls:
                    parsed = parse_data_uri(url)
                    if parsed:
                        mime_type, base64_data = parsed
                        gemini_user_parts.append(
                            {
                                "inline_data": {
                                    "mime_type": mime_type,
                                    "data": base64_data,
                                }
                            }
                        )
                    else:
                        logger.error(
                            f"Skipping invalid data URI for Gemini: {url[:50]}..."
                        )

            messages.append({"role": "user", "content": gemini_user_parts})

        elif route == "chutes" or route == "copilot":
            # --- Chutes.ai Route via LiteLLM ---
            litellm.api_key = api_key
            if route == "chutes":
                litellm.api_base = "https://llm.chutes.ai/v1"
            elif route == "copilot":
                litellm.api_base = "http://localhost:4141/"

            client = instructor.from_litellm(
                acompletion, mode=tool_mode_dict.get(tool_mode)
            )

            # Build messages for chutes/copilot (reset messages for this route)
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            user_content_parts = [{"type": "text", "text": content}]
            if image_urls:
                for url in image_urls:
                    user_content_parts.append(
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": url,
                            },
                        }
                    )
            messages.append({"role": "user", "content": user_content_parts})

        else:
            raise ValueError(f"Unsupported route: {route}")

        try:
            # Get appropriate rate limiter for this model
            model_limiter = get_model_limiter(model_key) if model_key else AsyncLimiter(1, 3)
            
            # Acquire the rate limiter before making the API call
            async with model_limiter:
                start_time = time.time()

                # Make the API call using the prepared messages
                if route == "openai" and reasoning:
                    response = await client.chat.completions.create(
                        model=model,
                        messages=messages,
                        response_model=response_model,
                        reasoning_effort=reasoning,
                    )
                elif route == "gemini":
                    response = await client.chat.completions.create(
                        messages=messages,
                        response_model=response_model,
                    )
                else:
                    response = await client.chat.completions.create(
                        model=model,
                        messages=messages,
                        response_model=response_model,
                    )


                elapsed_time = time.time() - start_time
                if route == "openrouter":
                    keys_tried_in_current_attempt.clear()
                if should_cache:
                    # Store as JSON string
                    if hasattr(response, "json"):
                        cache.set(cache_key, response.json(), expire=60 * 60 * 24 * 14)
                    elif isinstance(response, list) and hasattr(response[0], "dict"):
                        cache.set(
                            cache_key,
                            json.dumps([r.dict() for r in response]),
                            expire=60 * 60 * 24 * 14,
                        )
                    else:
                        cache.set(cache_key, response, expire=60 * 60 * 24 * 14)
                return response

        except Exception as e:
            # Check if this is a rate limit error or server error
            if is_rate_limit_error(e):
                logger.warning(
                    f"Rate limit error detected with key index {current_key_index} for route {route}"
                )
                _handle_rate_limit(e)
                raise e
            elif is_server_error(e):
                logger.warning(
                    f"Server error (500) detected with key index {current_key_index} for route {route}"
                )
                _handle_server_error(e)
                raise e
            else:
                logger.error(
                    f"Non-retryable error during API call for route {route}: {e}",
                    exc_info=True,
                )
                if route == "openrouter":
                    keys_tried_in_current_attempt.clear()
                raise

    def _handle_rate_limit(e: Exception):
        """Handle rate limit errors by determining whether to wait or rotate keys."""
        nonlocal current_key_index

        delay_needed = extract_retry_seconds(e)

        # Only rotate keys for OpenRouter if no specific delay is given and keys exist
        if route == "openrouter" and delay_needed is None and total_keys > 0:
            next_key_index = (current_key_index + 1) % total_keys
            while (
                next_key_index in keys_tried_in_current_attempt
                and len(keys_tried_in_current_attempt) < total_keys
            ):
                next_key_index = (next_key_index + 1) % total_keys

            if next_key_index != current_key_index:
                logger.info(
                    f"Rate limit requires key rotation. Switching to key index {next_key_index} for next attempt."
                )
                current_key_index = next_key_index
            else:
                logger.warning(
                    f"Rate limit requires key rotation, but all keys already tried in this cycle. Will retry with key {current_key_index} after minimal delay."
                )
        elif delay_needed is not None:
            logger.info(
                f"Rate limit requires specific delay. Waiting {delay_needed:.2f}s before next attempt (handled by tenacity)."
            )
        else:
            logger.info(
                f"Rate limit encountered on route {route}. Tenacity will handle wait based on custom_wait logic."
            )

    def _handle_server_error(e: Exception):
        """Handle server errors (HTTP 500) by rotating keys (only for OpenRouter)."""
        nonlocal current_key_index

        # Only rotate keys for OpenRouter if keys exist
        if route == "openrouter" and total_keys > 0:
            next_key_index = (current_key_index + 1) % total_keys

            while (
                next_key_index in keys_tried_in_current_attempt
                and len(keys_tried_in_current_attempt) < total_keys
            ):
                next_key_index = (next_key_index + 1) % total_keys

            if next_key_index != current_key_index:
                logger.info(
                    f"Server error requires key rotation. Switching to key index {next_key_index} for next attempt."
                )
                current_key_index = next_key_index
            else:
                logger.critical(
                    f"SERVER ERROR: All {total_keys} OpenRouter API keys have failed with server errors. Will retry with key {current_key_index} after minimal delay."
                )
        else:
            logger.warning(
                f"Server error encountered on route {route}. Tenacity will retry."
            )

    # Execute with retries
    try:
        return await _execute_with_retry()
    except tenacity.RetryError as e:
        attempts = (max_retries * total_keys + 1) if total_keys > 0 else max_retries + 1
        logger.error(
            f"API call failed for route {route} after multiple retries ({attempts} attempts): {e}",
            exc_info=True,
        )
        raise


