# %% Imports
import asyncio  # Added asyncio
import hashlib
import json
import logging
import os  # Added os

if os.name == "nt":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
import re
import time
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional, Set, Tuple, Type, TypeVar, Union
from urllib.parse import quote_plus, unquote

import diskcache
import google.generativeai as genai
import httpx
import instructor
import tenacity
from aiolimiter import AsyncLimiter  # Added aiolimiter
from config_llm import JINA_BASE_URL, OPENROUTER_API_KEYS, URL_CACHE
from dotenv import load_dotenv
from openai import AsyncOpenAI
from openai import RateLimitError as OpenAIRateLimitError  # Import openai's error
from openai._exceptions import APIStatusError
from pydantic import BaseModel, Field
from tenacity import (
    RetryCallState,
    before_sleep_log,
    retry,
    retry_if_exception,
    stop_after_attempt,
)
import litellm
from litellm import acompletion
from copy import deepcopy

litellm._logging._disable_debugging()


# Define your desired rate limit (e.g., 60 requests per 60 seconds)
# You might want to move this to config_llm.py
LLM_API_RATE_LIMIT = 1  # Requests per minute
LLM_API_RATE_PERIOD = 2  # Seconds

# Create the rate limiter instance
# This limiter will be shared across all calls using this module
llm_limiter = AsyncLimiter(LLM_API_RATE_LIMIT, LLM_API_RATE_PERIOD)


genai.configure(api_key="AIzaSyA6VcT0WFKyHhzevEsGibasEXi394UU6FY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")


# %% Helper function to parse data URI
def parse_data_uri(uri: str) -> Optional[Tuple[str, str]]:
    """Parses a data URI (e.g., 'data:image/jpeg;base64,...') into mime type and base64 data."""
    match = re.match(r"data:(?P<mime_type>[^;]+);base64,(?P<data>.*)", uri)
    if match:
        return match.group("mime_type"), match.group("data")
    logger.warning(f"Could not parse data URI: {uri[:50]}...")
    return None


async def close_httpx_client():
    await HTTPX_CLIENT.aclose()


# %% Setup Logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# %% Environment and Constants
load_dotenv()
JINA_API_KEY = "jina_cb0a7bc80b514d6088394156373e96dc1JeC0D7OJXMdLJvV_b_TCZhfzrUi"

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
# Ensure OPENROUTER_API_KEYS is loaded correctly as a list
if not isinstance(OPENROUTER_API_KEYS, list):
    # Log error but don't raise immediately, handle in the function if route='openrouter'
    logger.error("OPENROUTER_API_KEYS is not a list in config_llm.py.")
    OPENROUTER_API_KEYS = []  # Set to empty list to avoid errors if not used

# %% HTTPX Client (Removed AsyncRateLimitedTransport)
TIMEOUT_CONFIG = httpx.Timeout(10.0, read=180.0)
# Removed the transport argument
HTTPX_CLIENT = httpx.AsyncClient(timeout=TIMEOUT_CONFIG)


# %% Diskcache setup for persistent caching
CACHE_DIR = os.path.join(os.path.dirname(__file__), ".cache")
cache = diskcache.Cache(CACHE_DIR)


# %%
def clear_cache():
    """Clear all entries from the diskcache.

    Use this function to reset the cache when needed, such as when testing
    or when cache data becomes outdated.
    """
    try:
        count_before = len(cache)
        cache.clear()
        logger.info(f"Cache cleared successfully. Removed {count_before} entries.")
        return True
    except Exception as e:
        logger.error(f"Error clearing cache: {str(e)}")
        return False


# Example usage
# clear_cache()  # Uncomment to clear the cache


# %% get_link_markdown (Keep as is, added logging)
async def get_link_markdown(
    url: str, post: bool = False, use_cache: bool = True
) -> Optional[str]:
    """Convert URL content to markdown using Jina API via httpx, with diskcache."""
    url = unquote(url)  # Ensure URL is decoded before use

    if use_cache:
        cache_key = f"jina:{url}"
        cached = cache.get(cache_key)
        if cached is not None:
            logger.info(f"[CACHE HIT] Jina API for URL: {url}")
            return cached

    # logger.debug(f"Fetching markdown for URL: {url}")
    try:
        encoded_url = quote_plus(url)
        headers = {
            "Authorization": f"Bearer {JINA_API_KEY}",
            "X-Timeout": "300",
            "X-Respond-With": "readerlm-v2",
            "X-Base": "final",  # follows redirects
            "X-Return-Format": "markdown",  # html returns a very long response, not going to work, text doesn't get the full response
            # "X-Wait-For-Selector": "body, span",
            "X-Retain-Images": "none",
            "X-No-Cache": "true",
            "X-Proxy": "auto",
            "X-With-Iframe": "true",
            "X-With-Shadow-Dom": "true",
            "X-Engine": "cf-browser-rendering",
            # "Accept": "text/event-stream",  # Stream format
        }
        if post:
            data = {
                "url": f"{encoded_url}",
                "instruction": 'Return all event-related information comprehensively. If no such information, just return "Not event related".',
            }

        start_time = time.time()
        if post:
            response = await HTTPX_CLIENT.post(
                f"{JINA_BASE_URL}{encoded_url}", headers=headers, json=data
            )
        else:
            response = await HTTPX_CLIENT.get(
                f"{JINA_BASE_URL}{encoded_url}", headers=headers
            )
        elapsed_time = time.time() - start_time
        logger.info(f"Jina API response in {elapsed_time:.2f} seconds")

        if response.status_code == 200:
            content = response.text
            if use_cache:
                cache.set(cache_key, content, expire=60 * 60 * 24 * 7)  # 1 week expiry
            return content
        else:
            error_detail = response.text if response.text else "No details"
            logger.error(
                f"Error fetching URL {url}: Status {response.status_code} - {error_detail}"
            )
            response.raise_for_status()  # Raise for non-2xx

    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP error processing URL {url}: {e}")
        return None
    except httpx.RequestError as e:
        logger.error(f"Request error processing URL {url}: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error processing URL {url}: {str(e)}")
        return None


# %% Helper Functions for Tenacity Retry Logic


# Updated function to parse specific error structures
def extract_retry_seconds(exc: Exception) -> Optional[float]:
    """
    Extracts retry delay in seconds from rate limit errors.

    Prioritizes finding RetryInfo in the raw error data from Google AI Studio.

    Args:
        exc: The exception object.

    Returns:
        Delay in seconds as a float if found, otherwise None.
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


# Improved rate limit error detection
def is_rate_limit_error(exc: Exception) -> bool:
    """
    Checks if the exception is a rate limit error.

    Handles multiple rate limit error formats from OpenRouter and providers:
    1. OpenAI RateLimitError with status 429
    2. ValueError/InstructorRetryException with code 429
    3. Provider returned errors with code 429
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


# Updated custom wait strategy
def custom_wait(retry_state: RetryCallState) -> float:
    """
    Determines wait time based on the exception.

    Uses extract_retry_seconds to find a specific delay.
    If no specific delay, returns a minimal wait time for key rotation.
    """
    exc = retry_state.outcome.exception()
    if exc:
        delay = extract_retry_seconds(exc)
        if delay is not None:
            logger.info(f"Applying specific delay of {delay:.2f} seconds.")
            return delay  # Use the extracted delay

    # If no specific delay found or no exception (shouldn't happen with retry_if_exception)
    # Return a very short delay to allow the next attempt (potentially with a rotated key)
    logger.info("Applying minimal delay for next attempt (likely key rotation).")
    return 2


# Updated function to detect server errors (HTTP 500) in various exception formats
def is_server_error(exc: Exception) -> bool:
    """
    Checks if the exception is a server error (HTTP 500).

    Used to trigger key rotation for server errors.
    """
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


# %% Main Function using Tenacity
T = TypeVar("T", bound=BaseModel)


async def instructor_chat_completion(
    model: str,
    response_model: Union[Type[T], List[Type[T]]],
    content: str,
    image_urls: Optional[List[str]] = None,
    system_prompt: Optional[str] = None,
    tool_mode: Optional[str] = "tools",
    require_params: bool = True,
    max_retries: int = 5,
    route: Literal["openrouter", "gemini", "chutes", "copilot"] = "openrouter",
) -> T:
    """
    A wrapper function for instructor chat completion with robust retry handling and diskcache for image-based calls.

    Automatically handles rate limiting with appropriate retries (specific delay or
    key rotation) based on error details. Includes explicit rate limiting via aiolimiter.

    Args:
        model: The model identifier string
        response_model: Pydantic model(s) for structured response
        content: The text content for the request
        image_urls: Optional list of image URLs to include
        system_prompt: Optional system prompt
        tool_mode: The instructor tool mode (e.g. "tools", "json", "md_json", "json_schema",)
        require_params: Whether to require parameters in the request
        max_retries: Maximum number of retry attempts (per key effectively)
        route: Selects the API route ('openrouter', 'gemini', 'chutes', or 'copilot').

    Returns:
        Structured response as the specified Pydantic model
    """
    # tool_mode dict
    tool_mode_dict = {
        "tools": instructor.Mode.TOOLS,  # If tool calling is supported
        "json": instructor.Mode.JSON,  # If tool calling is not supported
        "md_json": instructor.Mode.MD_JSON,
        "json_schema": instructor.Mode.JSON_SCHEMA,
        #
        "gemini_json": instructor.Mode.GEMINI_JSON,  # If tool calling is not supported in Gemini (multimodal)
        "gemini_tools": instructor.Mode.GEMINI_TOOLS,
        #
        "anthropic_tools": instructor.Mode.ANTHROPIC_TOOLS,
    }

    # Shared state across retries
    current_key_index = 0
    keys_tried_in_current_attempt: Set[int] = set()  # Track keys per attempt sequence
    # Ensure OPENROUTER_API_KEYS is not empty before calculating total_keys
    total_keys = len(OPENROUTER_API_KEYS) if OPENROUTER_API_KEYS else 0
    if total_keys == 0 and route == "openrouter":
        logger.error(
            "No OpenRouter API keys available, cannot proceed with OpenRouter route."
        )
        # Raise error here as it's a configuration issue
        raise ValueError("OpenRouter API keys are not configured or empty.")

    # Pre-build messages (static part of request)
    messages = [{"role": "system", "content": system_prompt}] if system_prompt else []
    user_content_parts = [{"type": "text", "text": content}]
    if image_urls:
        user_content_parts.extend(
            {"type": "image_url", "image_url": {"url": url}} for url in image_urls
        )
    messages.append({"role": "user", "content": user_content_parts})

    # Provider-specific options
    extra_body = {"provider": {"require_parameters": True}} if require_params else {}

    # Only cache image-based calls (not event extraction)
    should_cache = (
        bool(image_urls)
        and len(image_urls) == 1
        and image_urls[0].startswith("data:image")
    )
    if should_cache:
        img_hash = hashlib.sha256(image_urls[0].encode("utf-8")).hexdigest()
        cache_key = f"img:{model}:{tool_mode}:{content[:40]}:{img_hash}"
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
        wait=custom_wait,  # Use the updated custom wait logic
        stop=stop_after_attempt(
            # Adjust stop condition if total_keys could be 0
            (max_retries * total_keys + 1)
            if total_keys > 0
            else max_retries + 1
        ),  # Allow retries across all keys
        before_sleep=before_sleep_log(logger, logging.INFO),
        reraise=True,
    )
    async def _execute_with_retry():
        nonlocal current_key_index, keys_tried_in_current_attempt
        nonlocal model

        # Ensure we have keys if using OpenRouter (already checked above, but good safeguard)
        if route == "openrouter" and total_keys == 0:
            raise ValueError("OpenRouter API keys are not configured or empty.")

        # Check if we've exhausted all keys in this attempt cycle (only if keys exist)
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
        elif route == "gemini":
            # Use the globally configured Gemini key
            api_key = os.getenv("GEMINI_API_KEY")
            if not api_key:
                logger.error("GEMINI_API_KEY environment variable not set.")
                raise ValueError("GEMINI_API_KEY is not configured.")
        elif route == "chutes" or route == "copilot":
            # Use the LITELLM_API_KEY env var or fallback to the default chutes key
            api_key = os.getenv(
                "LITELLM_API_KEY",
                "cpk_124e1b76efc446f99bbc7041356768c4.60f6fe94168451c08dcd92b124e6b532.sebtU7pEmnZfMPyCq07NidXRaK5gQWn9",
            )
            if not api_key:
                logger.error(
                    "LITELLM_API_KEY environment variable not set and no fallback key available."
                )
                raise ValueError("LITELLM_API_KEY is not configured.")

        # logger.info(f"Attempting API call with key index {current_key_index} for route {route}")

        # Create client and prepare messages based on route
        client = None
        messages = []  # Initialize messages list

        if route == "openrouter":
            # --- OpenRouter Route ---
            client = instructor.patch(
                AsyncOpenAI(
                    base_url="https://openrouter.ai/api/v1",
                    api_key=api_key,
                    max_retries=0,  # Disable client's built-in retries, use tenacity
                    http_client=HTTPX_CLIENT,  # Pass the shared client
                ),
                mode=tool_mode_dict.get(tool_mode),
            )
            # Build messages for OpenRouter
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
            # google_search_tool = Tool(google_search = GoogleSearch())
            genai_model = genai.GenerativeModel(model_name=f"models/{model}")
            client = instructor.from_gemini(
                client=genai_model,
                mode=instructor.Mode.GEMINI_JSON,
                use_async=True,
            )

            # Build messages/contents for Gemini
            # Prepend system prompt to user content if present
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
                        # Decide how to handle parse errors: skip image, raise error, etc.
                        # For now, we log and skip.

            # Instructor's from_gemini expects the 'messages' format,
            # but the content should be structured for Gemini's parts.
            # Note: System prompt is handled by prepending to user text.
            messages.append({"role": "user", "content": gemini_user_parts})

        elif route == "chutes" or route == "copilot":
            # --- Chutes.ai Route via LiteLLM ---
            # Set up LiteLLM config
            litellm.api_key = api_key
            if route == "chutes":
                litellm.api_base = "https://llm.chutes.ai/v1"
            elif route == "copilot":
                litellm.api_base = "http://localhost:4141/"

            # Create client using instructor with litellm
            client = instructor.from_litellm(
                acompletion, mode=tool_mode_dict.get(tool_mode)
            )

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
            # Acquire the rate limiter before making the API call
            async with llm_limiter:
                start_time = time.time()
                response = None

                # Make the API call using the prepared messages
                # Instructor should handle the conversion for the respective client.
                if route == "chutes" or route == "copilot":
                    # For chutes/copilot route, use litellm's format
                    # Note: require_params is OpenRouter-specific and is ignored for LiteLLM routes
                    response = await client.chat.completions.create(
                        model=model,
                        messages=messages,
                        response_model=response_model,
                    )
                else:

                    # For other routes (openrouter, gemini)
                    response = await client.chat.completions.create(
                        messages=messages,
                        response_model=response_model,
                        # Add model only if needed by the specific client's create method
                        **({"model": model} if route == "openrouter" else {}),
                        # Add extra_body only for OpenRouter
                        **(
                            {"extra_body": extra_body}
                            if route == "openrouter" and extra_body
                            else {}
                        ),
                    )

                elapsed_time = time.time() - start_time
                # logger.info(f"Response time: {elapsed_time:.2f}s for route {route}")
                if route == "openrouter":
                    keys_tried_in_current_attempt.clear()  # Reset tried keys on success
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
                _handle_rate_limit(e)  # Pass the exception object
                raise e  # Re-raise for tenacity
            elif is_server_error(e):
                logger.warning(
                    f"Server error (500) detected with key index {current_key_index} for route {route}"
                )
                _handle_server_error(e)  # Pass the exception object
                raise e  # Re-raise for tenacity
            else:
                # Not a rate limit or server error
                logger.error(
                    f"Non-retryable error during API call for route {route}: {e}",
                    exc_info=True,  # Log traceback
                )
                if route == "openrouter":
                    keys_tried_in_current_attempt.clear()  # Reset on non-retryable error for OpenRouter
                raise  # Re-raise other errors

    def _handle_rate_limit(e: Exception):  # Added type hint
        """Handle rate limit errors by determining whether to wait or rotate keys."""
        nonlocal current_key_index

        delay_needed = extract_retry_seconds(e)

        # Only rotate keys for OpenRouter if no specific delay is given and keys exist
        if route == "openrouter" and delay_needed is None and total_keys > 0:
            # No specific delay found or delay is too long, rotate key for the *next* attempt
            next_key_index = (current_key_index + 1) % total_keys
            # Avoid immediately retrying the same key if rotation brings us back
            while (
                next_key_index in keys_tried_in_current_attempt
                and len(keys_tried_in_current_attempt) < total_keys
            ):
                next_key_index = (next_key_index + 1) % total_keys

            if next_key_index != current_key_index:  # Only log if key actually changes
                logger.info(
                    f"Rate limit requires key rotation. Switching to key index {next_key_index} for next attempt."
                )
                current_key_index = next_key_index
            else:
                logger.warning(
                    f"Rate limit requires key rotation, but all keys already tried in this cycle. Will retry with key {current_key_index} after minimal delay."
                )
        elif delay_needed is not None:
            # Specific delay found, tenacity's `custom_wait` will handle the sleep
            logger.info(
                f"Rate limit requires specific delay. Waiting {delay_needed:.2f}s before next attempt (handled by tenacity)."
            )
        else:
            # For Gemini or OpenRouter with no keys/no rotation needed
            logger.info(
                f"Rate limit encountered on route {route}. Tenacity will handle wait based on custom_wait logic."
            )
        # Key index does not change here

    def _handle_server_error(e: Exception):  # Added type hint
        """Handle server errors (HTTP 500) by rotating keys (only for OpenRouter)."""
        nonlocal current_key_index

        # Only rotate keys for OpenRouter if keys exist
        if route == "openrouter" and total_keys > 0:
            # For server errors, we always rotate keys instead of waiting
            next_key_index = (current_key_index + 1) % total_keys

            # Avoid immediately retrying the same key if rotation brings us back
            while (
                next_key_index in keys_tried_in_current_attempt
                and len(keys_tried_in_current_attempt) < total_keys
            ):
                next_key_index = (next_key_index + 1) % total_keys

            if next_key_index != current_key_index:  # Only log if key actually changes
                logger.info(
                    f"Server error requires key rotation. Switching to key index {next_key_index} for next attempt."
                )
                current_key_index = next_key_index
            else:
                logger.critical(
                    f"SERVER ERROR: All {total_keys} OpenRouter API keys have failed with server errors. Will retry with key {current_key_index} after minimal delay."
                )
        else:
            # For Gemini or OpenRouter with no keys
            logger.warning(
                f"Server error encountered on route {route}. Tenacity will retry."
            )

    # Execute with retries
    try:
        return await _execute_with_retry()
    except tenacity.RetryError as e:
        # Adjust error message if total_keys could be 0
        attempts = (max_retries * total_keys + 1) if total_keys > 0 else max_retries + 1
        logger.error(
            f"API call failed for route {route} after multiple retries ({attempts} attempts): {e}",
            exc_info=True,  # Log final exception
        )
        raise  # Re-raise the final RetryError


# %%

# Flaresolverr Client


class AsyncFlaresolverrClient:
    """
    An async Python client for interacting with a Flaresolverr instance.
    Manages session creation, requests, and destruction with robust session management.
    """

    def __init__(self, flaresolverr_url: str = "http://localhost:8191/v1"):
        """
        Initializes the client.

        Args:
            flaresolverr_url: The base URL of the Flaresolverr API.
        """
        self.base_url = flaresolverr_url
        self.active_sessions: Dict[str, str] = {}
        self.session_failure_file = os.path.join(
            os.path.dirname(__file__), "session_failures.csv"
        )
        self.session_failures: Dict[str, List[bool]] = (
            {}
        )  # session_id -> list of recent results (True=success, False=failure)
        self.session_counter = 0  # For generating new session IDs
        self.load_session_failures()

    def load_session_failures(self):
        """Load session failure history from CSV file."""
        try:
            if os.path.exists(self.session_failure_file):
                import csv

                with open(self.session_failure_file, "r", newline="") as f:
                    reader = csv.reader(f)
                    for row in reader:
                        if len(row) >= 2:
                            session_id = row[0]
                            # Parse recent failures as boolean list (last 5 attempts)
                            failures_str = row[1] if len(row) > 1 else ""
                            failures = []
                            for char in failures_str[-5:]:  # Only keep last 5
                                if char == "1":
                                    failures.append(True)  # Success
                                elif char == "0":
                                    failures.append(False)  # Failure
                            self.session_failures[session_id] = failures
                logger.info(
                    f"Loaded session failure history for {len(self.session_failures)} sessions"
                )
        except Exception as e:
            logger.warning(f"Could not load session failures: {e}")
            self.session_failures = {}

    def save_session_failures(self):
        """Save session failure history to CSV file."""
        try:
            import csv

            with open(self.session_failure_file, "w", newline="") as f:
                writer = csv.writer(f)
                for session_id, failures in self.session_failures.items():
                    # Convert boolean list to string (1=success, 0=failure)
                    failures_str = "".join(
                        "1" if success else "0" for success in failures[-5:]
                    )
                    writer.writerow([session_id, failures_str])
        except Exception as e:
            logger.warning(f"Could not save session failures: {e}")

    def record_session_result(self, session_id: str, success: bool):
        """Record the result of a session attempt."""
        if session_id not in self.session_failures:
            self.session_failures[session_id] = []

        # Add result and keep only last 5 attempts
        self.session_failures[session_id].append(success)
        self.session_failures[session_id] = self.session_failures[session_id][-5:]

        # Save to file
        self.save_session_failures()

    def is_session_retired(self, session_id: str) -> bool:
        """Check if a session should be retired (5 consecutive failures)."""
        if session_id not in self.session_failures:
            return False

        failures = self.session_failures[session_id]
        # Check if we have 5 attempts and all are failures
        return len(failures) >= 5 and not any(failures)

    def get_active_session_ids(self) -> List[str]:
        """Get list of session IDs that are not retired (only first 2 base sessions)."""
        active_sessions = []

        # Only try the first 2 base session names - 3rd will be unique per URL
        base_sessions = ["flare_session_1", "flare_session_2"]

        for session_id in base_sessions:
            if not self.is_session_retired(session_id):
                active_sessions.append(session_id)

        # If we need more sessions (all base sessions retired), create new ones
        if len(active_sessions) < 2:
            needed = 2 - len(active_sessions)
            for i in range(needed):
                self.session_counter += 1
                new_session_id = f"flare_session_{self.session_counter}"
                active_sessions.append(new_session_id)

        return active_sessions

    def get_url_pathways(self, url: str) -> List[Tuple[Optional[str], int]]:
        """
        Get the 4 pathways for URL processing: 2 tracked sessions + 1 unique URL session + 1 no-session.
        Each pathway is tried twice. No-session is tried last as a fallback.

        Returns:
            List of tuples (session_id, attempt_number) for each pathway
        """
        pathways = []

        # Pathways 1-2: Active tracked sessions (2 attempts each)
        active_sessions = self.get_active_session_ids()
        for session_id in active_sessions[:2]:  # Only use first 2 active sessions
            pathways.extend([(session_id, 1), (session_id, 2)])

        # Pathway 3: Unique URL-specific session (2 attempts) - NOT tracked for failures
        import hashlib

        url_hash = hashlib.md5(url.encode()).hexdigest()[:8]
        unique_session_id = f"flare_url_{url_hash}"
        pathways.extend([(unique_session_id, 1), (unique_session_id, 2)])

        # Pathway 4: No session (2 attempts) - as last resort
        pathways.extend([(None, 1), (None, 2)])

        return pathways

    async def create_session(self, session_id: str) -> bool:
        """
        Creates a new browser session in Flaresolverr.

        Args:
            session_id: A unique name for the session.

        Returns:
            True if the session was created successfully, False otherwise.
        """
        logger.info(f"Creating Flaresolverr session: {session_id}")
        payload = {"cmd": "sessions.create", "session": session_id}

        try:
            response = await HTTPX_CLIENT.post(self.base_url, json=payload, timeout=30)
            response.raise_for_status()
            data = response.json()

            if data.get("status") == "ok":
                self.active_sessions[session_id] = session_id
                logger.info(f"Session '{session_id}' created successfully")
                return True
            else:
                logger.error(f"Error creating session: {data.get('message')}")
                return False

        except httpx.RequestError as e:
            logger.error(f"Failed to connect to Flaresolverr: {e}")
            return False

    def create_session_sync(self, session_id: str) -> bool:
        """
        Synchronously creates a new browser session in Flaresolverr.

        Args:
            session_id: A unique name for the session.

        Returns:
            True if the session was created successfully, False otherwise.
        """
        logger.info(f"Creating Flaresolverr session (sync): {session_id}")
        payload = {"cmd": "sessions.create", "session": session_id}

        try:
            response = requests.post(self.base_url, json=payload, timeout=30)
            response.raise_for_status()
            data = response.json()

            if data.get("status") == "ok":
                self.active_sessions[session_id] = session_id
                logger.info(f"Session '{session_id}' created successfully")
                return True
            else:
                logger.error(f"Error creating session: {data.get('message')}")
                return False

        except requests.RequestException as e:
            logger.error(f"Failed to connect to Flaresolverr: {e}")
            return False

    async def get_url(
        self,
        url: str,
        session_id: Optional[str] = None,
        timeout_ms: int = 120000,
        use_cache: bool = True,
    ) -> Optional[str]:
        """
        Fetches a URL, optionally using an existing session, with diskcache support.

        Args:
            url: The URL to fetch.
            session_id: The session to use. If None, a session-less request is made.
            timeout_ms: Timeout for the request in milliseconds.
            use_cache: Whether to use cached results if available.

        Returns:
            The HTML content of the page as a string, or None if it failed.
        """
        # Check cache first
        if use_cache:
            cache_key = f"flaresolverr:{url}"
            cached = cache.get(cache_key)
            if cached is not None:
                # logger.info(f"[CACHE HIT] Flaresolverr for URL: {url}")
                return cached

        # logger.info(
        #     f"Requesting URL: {url} {'with session ' + session_id if session_id else ''}"
        # )
        payload = {"cmd": "request.get", "url": url, "maxTimeout": timeout_ms}

        if session_id and session_id in self.active_sessions:
            payload["session"] = session_id

        try:
            response = await HTTPX_CLIENT.post(
                self.base_url, json=payload, timeout=(timeout_ms / 1000) + 10
            )
            response.raise_for_status()
            data = response.json()

            if data.get("status") == "ok":
                html_content = data["solution"]["response"]

                # Check for Cloudflare challenges before caching
            if not any(
                challenge in html_content
                for challenge in [
                    "https://challenges.cloudflare.com/cdn-cgi/",
                    "/cdn-cgi/challenge-platform",
                    "/cdn-cgi/styles/cf.errors.css",
                ]
            ):
                # Only cache successful responses without Cloudflare challenges
                if use_cache:
                    cache.set(
                        cache_key, html_content, expire=60 * 60 * 24 * 3
                    )  # 3 days expiry
                    # logger.info(f"[CACHE SET] Flaresolverr for URL: {url}")

                # logger.info("URL fetched successfully")
                return html_content
            else:
                logger.error(
                    f"Flaresolverr returned an error for {url}: {data.get('message')}"
                )
                return None

        except httpx.RequestError as e:
            logger.error(f"Failed to fetch {url}: {e}")
            return None

    def get_url_sync(
        self,
        url: str,
        session_id: Optional[str] = None,
        timeout_ms: int = 120000,
        use_cache: bool = True,
    ) -> Optional[str]:
        """
        Synchronously fetches a URL using robust session management with automatic retry pathways and diskcache support.

        This method implements 4 pathways:
        1. No session (2 attempts)
        2-4. Three tracked sessions (2 attempts each)

        Sessions are automatically retired after 5 consecutive failures.

        Args:
            url: The URL to fetch.
            session_id: Legacy parameter - ignored in favor of automatic session management.
            timeout_ms: Timeout for the request in milliseconds.
            use_cache: Whether to use cached results if available.

        Returns:
            The HTML content of the page as a string, or None if all pathways failed.
        """
        # Check cache first
        if use_cache:
            cache_key = f"flaresolverr:{url}"
            cached = cache.get(cache_key)
            if cached is not None:
                # logger.info(f"[CACHE HIT] Flaresolverr for URL: {url}")
                return cached

        pathways = self.get_url_pathways(url)
        last_error = None

        # logger.info(f"Processing URL with {len(pathways)} pathway attempts: {url}")

        for i, (pathway_session_id, attempt_num) in enumerate(pathways):
            try:
                # Create session if it doesn't exist and is not None
                if (
                    pathway_session_id
                    and pathway_session_id not in self.active_sessions
                ):
                    success = self.create_session_sync(pathway_session_id)
                    if not success:
                        logger.warning(
                            f"Failed to create session {pathway_session_id}, skipping"
                        )
                        continue

                # Build payload
                payload = {"cmd": "request.get", "url": url, "maxTimeout": timeout_ms}
                if pathway_session_id and pathway_session_id in self.active_sessions:
                    payload["session"] = pathway_session_id

                # Make request
                import requests

                response = requests.post(
                    self.base_url, json=payload, timeout=(timeout_ms / 1000) + 10
                )
                response.raise_for_status()
                data = response.json()

                if data.get("status") == "ok":
                    html_content = data["solution"]["response"]

                    # Check for Cloudflare challenges
                    if any(
                        challenge in html_content
                        for challenge in [
                            "https://challenges.cloudflare.com/cdn-cgi/",
                            "/cdn-cgi/challenge-platform",
                            "/cdn-cgi/styles/cf.errors.css",
                        ]
                    ):
                        # logger.warning(f"Cloudflare challenge detected for {url} with {'no session' if not pathway_session_id else pathway_session_id}")
                        # Only record failures for tracked sessions (not URL-specific ones)
                        if pathway_session_id and not pathway_session_id.startswith(
                            "flare_url_"
                        ):
                            self.record_session_result(pathway_session_id, False)
                        last_error = "Cloudflare challenge still present"
                        continue

                    # Success!
                    # Only record success for tracked sessions (not URL-specific ones)
                    if pathway_session_id and not pathway_session_id.startswith(
                        "flare_url_"
                    ):
                        self.record_session_result(pathway_session_id, True)

                    # Cache successful result
                    if use_cache:
                        cache_key = f"flaresolverr:{url}"
                        cache.set(
                            cache_key, html_content, expire=60 * 60 * 24 * 3
                        )  # 3 days expiry
                        # logger.info(f"[CACHE SET] Flaresolverr for URL: {url}")

                    # logger.info(f"Successfully fetched {url} using {'no session' if not pathway_session_id else pathway_session_id} (attempt {attempt_num})")
                    return html_content
                else:
                    error_msg = data.get("message", "Unknown error")
                    # logger.warning(f"Flaresolverr error for {url} with {'no session' if not pathway_session_id else pathway_session_id}: {error_msg}")
                    # Only record failures for tracked sessions (not URL-specific ones)
                    if pathway_session_id and not pathway_session_id.startswith(
                        "flare_url_"
                    ):
                        self.record_session_result(pathway_session_id, False)
                    last_error = error_msg

            except requests.RequestException as e:
                # logger.warning(f"Request error for {url} with {'no session' if not pathway_session_id else pathway_session_id}: {e}")
                # Only record failures for tracked sessions (not URL-specific ones)
                if pathway_session_id and not pathway_session_id.startswith(
                    "flare_url_"
                ):
                    self.record_session_result(pathway_session_id, False)
                last_error = str(e)

            except Exception as e:
                logger.warning(
                    f"Unexpected error for {url} with {'no session' if not pathway_session_id else pathway_session_id}: {e}"
                )
                # Only record failures for tracked sessions (not URL-specific ones)
                if pathway_session_id and not pathway_session_id.startswith(
                    "flare_url_"
                ):
                    self.record_session_result(pathway_session_id, False)
                last_error = str(e)

            # Add delay between attempts (except for last attempt)
            if i < len(pathways) - 1:
                import time
                import random

                time.sleep(random.uniform(3.0, 5.0))

        logger.error(f"All pathways failed for {url}. Last error: {last_error}")
        return None

    async def destroy_session(self, session_id: str) -> bool:
        """
        Destroys a browser session in Flaresolverr.

        Args:
            session_id: The name of the session to destroy.

        Returns:
            True if successful, False otherwise.
        """
        if session_id not in self.active_sessions:
            logger.warning(f"Session '{session_id}' not found")
            return False

        logger.info(f"Destroying Flaresolverr session: {session_id}")
        payload = {"cmd": "sessions.destroy", "session": session_id}

        try:
            response = await HTTPX_CLIENT.post(self.base_url, json=payload, timeout=30)
            response.raise_for_status()
            data = response.json()

            if data.get("status") == "ok":
                del self.active_sessions[session_id]
                logger.info(f"Session '{session_id}' destroyed successfully")
                return True
            else:
                logger.error(f"Error destroying session: {data.get('message')}")
                return False

        except httpx.RequestError as e:
            logger.error(f"Failed to destroy session: {e}")
            return False

    async def __aenter__(self):
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit - cleanup all sessions."""
        for session_id in list(self.active_sessions.keys()):
            await self.destroy_session(session_id)


# %%

# Crawl4AI 2nd Test

import asyncio

# import nest_asyncio
import os
from datetime import datetime

import instructor
import litellm
from crawl4ai import *
from crawl4ai.async_dispatcher import MemoryAdaptiveDispatcher, SemaphoreDispatcher
from crawl4ai.content_scraping_strategy import LXMLWebScrapingStrategy
from crawl4ai.deep_crawling.filters import (
    ContentRelevanceFilter,
    ContentTypeFilter,
    FilterChain,
    SEOFilter,
)
import requests
import random
import string

# litellm.enable_json_schema_validation = True

# nest_asyncio.apply()

urls = [
    "https://underline.center/t/maestro-impro-by-improv-lore/110",
    "https://underline.center/t/swapbook-bengaluru/309",
    "https://in.bookmyshow.com/plays/patna-ka-superhero/ET00437436",
    "https://map-india.org/map-events/solve-the-puzzle-ticket-tika-chaap-2/",
    "https://app.venn.buzz/social_experience/4142",
    "https://in.bookmyshow.com/events/guns-n-roses-india-2025/ET00437140",
    "https://reuters.com",
]


class EventDetail(BaseModel):
    is_event: bool = Field(
        description="Whether the content is related to a public, attendable event. If False, leave the rest of the fields empty."
    )
    description: str = Field(
        description="Extensive, comprehensive information about the main event including (if details are available) the event date, time (in IST), location, cost and any other relevant information.",
        default="",
    )
    additional_links: List[str] = Field(
        default_factory=list,
        description="List of highly relevant links that are indicated to provide additional information about the specific event. These can include registration links, payment links or links with additional information. Do not include general links, calendar links or links that are not directly related to the event. Restrict the number of links to 2 or fewer. Leave empty if no such links are found.",
    )


class EventDetailNoLinks(BaseModel):
    is_event: bool = Field(
        description="Whether the content is related to a public, attendable event. If False, leave the rest of the fields empty."
    )
    description: str = Field(
        description="Extensive, comprehensive information about the main event including (if details are available) the event date, time (in IST), location, cost and any other relevant information.",
        default="",
    )


def is_blacklisted(url: str) -> bool:
    """Check if a URL should be blacklisted."""
    if not isinstance(url, str):
        return True

    url_lower = url.lower()
    bad_links = [
        "maps.app.goo.gl",
        "maps.google",
        "chat.whatsapp.com",
        "linktr.ee",
        "open.spotify",
        "api.whatsapp.com",
        "wa.me",
        "web.zoom.us",
    ]

    if any(domain in url_lower for domain in bad_links):
        return True

    # Special handling for Instagram: only allow post links (/p/)
    if "instagram.com" in url_lower and "/p/" not in url_lower:
        return True

    return False


async def process_markdown_with_llm(
    url: str,
    markdown_content: str,
    model_name: str,
    llm_call_limiter: AsyncLimiter,
    client,
    use_links_model: bool = True,
) -> dict:
    """Process markdown content with LLM to extract event details."""
    async with llm_call_limiter:
        try:
            process_response = {
                "llm_success": True,
                "llm_error": None,
                "llm_response": None,
            }

            system_prompt = (
                f"You are now an Event Information Extractor. Based on the above content from the URL, determine if it describes a public, attendable event."
                f"If it is an event, extract a comprehensive, verbose and extensive description about the event capturing all relevant details."
                f"Also, if the page provides the option to register or pay for an event, indicate it as a registration link. Else if it just provides information indicate that it is in info link."
                f"Based on the links in the page, add upto two additional links for further parsing that are likely to contain more information or registration about the event. Only links that are highly relevant."
            )

            system_prompt_no_links = (
                f"You are now an Event Information Extractor. Based on the above content from the URL, determine if it describes a public, attendable event."
                f"If it is an event, extract a comprehensive, verbose and extensive description about the event capturing all relevant details."
                f"Also, if the page provides the option to register or pay for an event, indicate it as a registration link. Else if it just provides information indicate that it is in info link."
            )

            # system_prompt = (
            #     f"You are now an Event Information Extractor. Based on the above content from the URL, determine if it describes a public, attendable event."
            #     f"If it is an event, extract a comprehensive, accurate, verbose and extensive description about the event capturing all relevant details."
            #     f"Also, if the page provides the option to register or pay for an event, indicate it as a registration link. Else if it just provides information indicate that it is in info link."
            # )

            # event_extraction = await client.chat.completions.create(
            #     model=model_name,
            #     response_model=response_model,
            #     messages=[{"role": "user", "content": prompt if use_links_model else prompt_no_links}],
            #     max_retries=1,
            # )

            model_name = "openai/deepseek-ai/DeepSeek-V3-0324"

            event_extraction = await instructor_chat_completion(
                model=model_name,
                response_model=EventDetail if use_links_model else EventDetailNoLinks,
                system_prompt=(
                    system_prompt if use_links_model else system_prompt_no_links
                ),
                content=f"URL: {url}\n\nContent:\n{markdown_content}\n\n",
                tool_mode="json",
                route="chutes",
            )

            process_response["llm_response"] = event_extraction.model_dump()
            return process_response

        except Exception as e:
            logger.error(f"LLM processing error for {url}: {str(e)}")
            # Create a default error response
            process_response["llm_success"] = False
            process_response["llm_error"] = str(e)
            return process_response


def get_html_cloudflare_link_sync(client, url, use_cache: bool = True):
    """
    Synchronously process a single URL through Flaresolverr using robust session management with caching.

    This function now uses the enhanced AsyncFlaresolverrClient with automatic pathway management and diskcache.
    The session_id and random_session_id parameters are kept for backward compatibility but ignored.

    Args:
        client: AsyncFlaresolverrClient instance
        url: Single URL to process
        use_cache: Whether to use cached results if available

    Returns:
        HTML content as string, or None if failed
    """
    logger.info(f"Processing URL: {url}")

    # Use the new robust get_url_sync method which handles all session management internally
    html_content = client.get_url_sync(url, use_cache=use_cache)

    if html_content is not None:
        logger.info(f"Successfully processed URL: {url}")
        return html_content
    else:
        logger.error(f"Failed to process URL after all pathways: {url}")
        return None


async def get_html_cloudflare_link(client, urls, session_id):
    # Create rate limiters for different retry cycles
    # More aggressive rate limiting for initial attempts, then relaxing for retries
    rate_limiters = [
        AsyncLimiter(1, 6),  # 1 request per 6 seconds (initial)
        AsyncLimiter(1, 12),  # 1 request per 12 seconds (1st retry)
        AsyncLimiter(1, 18),  # 1 request per 18 seconds (2nd retry)
        AsyncLimiter(1, 24),  # 1 request per 24 seconds (3rd retry)
    ]

    max_retries = 3
    current_urls = urls.copy()
    results = {}

    for attempt in range(max_retries + 1):
        if not current_urls:
            break

        current_limiter = rate_limiters[min(attempt, len(rate_limiters) - 1)]
        logger.info(
            f"Attempt {attempt + 1}/{max_retries + 1}: Processing {len(current_urls)} URLs with Flaresolverr"
        )

        async def fetch_with_limit(url: str, session_id: str):
            async with current_limiter:
                try:
                    return await client.get_url(url, session_id)
                except Exception as e:
                    logger.error(
                        f"Exception during Flaresolverr request for {url}: {e}"
                    )
                    return e

        # Execute requests with proper rate limiting
        html_results = await asyncio.gather(
            *[fetch_with_limit(url, session_id) for url in current_urls],
            return_exceptions=True,
        )

        # Process results and prepare failed URLs for retry
        failed_urls = []
        for url, html_content in zip(current_urls, html_results):
            if isinstance(html_content, Exception) or html_content is None:
                if attempt < max_retries:
                    logger.warning(
                        f"Failed to fetch {url} on attempt {attempt + 1}, will retry: {html_content}"
                    )
                    failed_urls.append(url)
                else:
                    logger.error(
                        f"Failed to fetch {url} after {max_retries + 1} attempts: {html_content}"
                    )
                    raise ValueError(
                        f"Failed to fetch {url} after {max_retries + 1} attempts: {html_content}"
                    )
            else:
                results[url] = html_content

        # Update URLs for next retry cycle
        current_urls = failed_urls

        if failed_urls and attempt < max_retries:
            wait_time = 4 * (attempt + 1)  # Exponential backoff between retry cycles
            logger.info(f"Waiting {wait_time} seconds before retry cycle {attempt + 2}")
            await asyncio.sleep(wait_time)

    logger.info(
        f"Flaresolverr processing complete: {len(results)} successful, {len(current_urls)} failed"
    )
    return results


async def crawl_and_process_url_many(
    urls: List[str],
    crawler,
    run_cfg: CrawlerRunConfig,
    flaresolverr_client: AsyncFlaresolverrClient,
    html_cfg: CrawlerRunConfig,
    dispatcher,
    model_name: str,
    llm_call_limiter: AsyncLimiter,
    client,
    use_links_model: bool = True,
) -> dict:
    """Crawl a URL and process the content with LLM."""

    results = []

    # First pass: Run crawler on all URLs
    pages = await crawler.arun_many(
        urls=urls,
        config=run_cfg,
        dispatcher=dispatcher,
    )

    # Detect Cloudflare challenges and handle them
    cloudflare_urls = []
    cloudflare_indices = []

    for i, (page, url) in enumerate(zip(pages, urls)):
        if any(
            challenge in page.html
            for challenge in [
                "https://challenges.cloudflare.com/cdn-cgi/",
                "/cdn-cgi/challenge-platform",
                "/cdn-cgi/styles/cf.errors.css",
            ]
        ):
            logger.warning(f"Cloudflare challenge detected for URL: {url}")
            cloudflare_urls.append(url)
            cloudflare_indices.append(i)

    # Handle Cloudflare challenges if any detected
    if cloudflare_urls:
        logger.info(
            f"Processing {len(cloudflare_urls)} URLs with Cloudflare challenges"
        )

        # await flaresolverr_client.create_session("crawl4ai_session")
        # await flaresolverr_client.create_session("crawl4ai_session_alt1")
        # random_session_id = ''.join(random.choices(string.ascii_letters + string.digits, k=10))
        # await flaresolverr_client.create_session(f"crawl4ai_session_{random_session_id}")

        html_results = {}

        logger.info(
            f"Fetching HTML content for {len(cloudflare_urls)} Cloudflare URLs using Flaresolverr"
        )

        for url in cloudflare_urls:
            result = get_html_cloudflare_link_sync(flaresolverr_client, url)
            if result:
                html_results[url] = result

        logger.info(
            f"Fetched HTML content for {len(html_results)} out of {len(cloudflare_urls)} Cloudflare URLs"
        )

        # Get HTML content using Flaresolverr
        # html_results = await get_html_cloudflare_link(
        #     flaresolverr_client, cloudflare_urls, "crawl4ai_session"
        # )

        # Process all Cloudflare HTML content in parallel using arun_many
        valid_cloudflare_data = []
        valid_indices = []

        for i, url in enumerate(cloudflare_urls):
            html_content = html_results.get(url)
            if html_content:
                valid_cloudflare_data.append((url, html_content))
                valid_indices.append(cloudflare_indices[i])
            else:
                logger.error(f"No HTML content received from Flaresolverr for {url}")
                # Replace with failed page
                pages[cloudflare_indices[i]].success = False
                pages[cloudflare_indices[i]].error_message = "No HTML from Flaresolverr"

        # Process all Cloudflare HTML content in parallel
        if valid_cloudflare_data:
            logger.info(
                f"Processing {len(valid_cloudflare_data)} Cloudflare pages for markdown extraction"
            )

            processed_pages = await asyncio.gather(
                *[
                    crawler.arun(
                        url=f"raw:{html_content}",
                        config=html_cfg,
                    )
                    for _, html_content in valid_cloudflare_data
                ],
                return_exceptions=True,
            )

            # Replace the original failed pages with processed ones
            for processed_page, page_index, (original_url, _) in zip(
                processed_pages, valid_indices, valid_cloudflare_data
            ):
                if isinstance(processed_page, Exception):
                    logger.error(
                        f"Exception processing Cloudflare page for {original_url}: {processed_page}"
                    )
                    pages[page_index].success = False
                    pages[page_index].error_message = (
                        f"Cloudflare processing exception: {str(processed_page)}"
                    )
                elif processed_page.success:
                    # Ensure the processed page maintains the original URL
                    processed_page.url = original_url
                    pages[page_index] = processed_page
                else:
                    logger.error(
                        f"Failed to process HTML content for {original_url}: {processed_page.error_message}"
                    )
                    pages[page_index].success = False
                    pages[page_index].error_message = (
                        f"Cloudflare processing error: {processed_page.error_message}"
                    )

    # Process each page result in parallel
    processing_tasks = []
    for page, url in zip(pages, urls):
        # Skip pages that still have Cloudflare challenges after processing
        if any(
            challenge in page.html
            for challenge in [
                "https://challenges.cloudflare.com/cdn-cgi/",
                "/cdn-cgi/challenge-platform",
                "/cdn-cgi/styles/cf.errors.css",
            ]
        ):
            logger.error(
                f"Cloudflare challenge still present after processing for URL: {url}"
            )

        if not page.success:
            results.append(
                {
                    "url": url,
                    "success": False,
                    "error_details": {
                        "source": "crawl4ai",
                        "status_code": page.status_code,
                        "page_markdown": page.markdown if page.markdown else "",
                    },
                    "event_details": {},
                }
            )
            logger.error(
                f"Failed to crawl {url}: {page.status_code} - {page.error_message}"
            )
            continue

        # Process the markdown content
        markdown_content = page.markdown.encode("utf-8", errors="ignore").decode(
            "utf-8"
        )

        # Create a task for LLM processing
        task = asyncio.create_task(
            process_markdown_with_llm(
                url,
                markdown_content,
                model_name,
                llm_call_limiter,
                client,
                use_links_model,
            )
        )
        processing_tasks.append((task, url))

    # Wait for all LLM processing to complete
    for task, url in processing_tasks:
        try:
            llm_resp = await task

            if not llm_resp["llm_success"]:
                results.append(
                    {
                        "url": url,
                        "success": False,
                        "error_details": {
                            "source": "llm",
                            "message": llm_resp["llm_error"],
                        },
                        "event_details": {},
                    }
                )
            else:
                results.append(
                    {
                        "url": url,
                        "success": True,
                        "event_details": llm_resp["llm_response"],
                    }
                )

        except Exception as e:
            error_msg = f"Error processing {url}: {str(e)}"
            logger.error(error_msg)
            results.append(
                {
                    "url": url,
                    "success": False,
                    "error_details": {
                        "source": "processing",
                        "message": error_msg,
                    },
                    "event_details": {},
                }
            )

    return results


async def crawl_and_extract_event_details_from_urls(urls: List[str]) -> Dict[str, Any]:
    """
    Crawl and extract event details from a list of URLs.

    Args:
        urls: List of URLs to process

    Returns:
        Dictionary mapping URLs to their processing results
    """
    if not urls:
        logger.warning("No URLs provided for crawling")
        return {}

    # urls = [url for url in urls if not any(dom in url for dom in ["://t.ly/", "://bit.ly/"])]

    logger.info(f"Processing {len(urls)} URLs using Crawl4AI")

    # user-data-dir setup
    project_root = os.path.dirname(os.path.dirname(__file__))
    user_data_path = os.path.join(project_root, "chrome_profile_crawl4ai")

    # user_data_path = r"C:\Users\rohit\AppData\Local\Google\Chrome\User Data\Profile 4"

    if not os.path.exists(user_data_path):
        raise FileNotFoundError(
            f"User data directory does not exist: {user_data_path}. Please create it before running the crawler."
        )

    # Setup configurations
    browser_cfg = BrowserConfig(
        # browser_type="chromium",
        # chrome_channel="chrome",
        # channel="chrome",
        headless=False,
        browser_mode="builtin",
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        ),
        use_persistent_context=True,
        # use_managed_browser=True,
        user_data_dir=user_data_path,
        viewport={"width": 1920, "height": 1080},  # Mimic a common desktop resolution.
        extra_args=[
            "--disable-blink-features=AutomationControlled",
            "--disable-infobars",
            "--start-maximized",
            "--disable-dev-shm-usage",
            # '--no-sandbox', # Often needed on Linux systems
            "--disable-setuid-sandbox",
        ],
        # --- Standard settings to maintain ---
        ignore_https_errors=True,
        # java_script_enabled=True,
    )

    dispatcher = SemaphoreDispatcher(
        semaphore_count=15,
        max_session_permit=20,
        rate_limiter=RateLimiter(
            base_delay=(4, 10),
            max_delay=30,
            max_retries=3,
            rate_limit_codes=[429, 503, 504],
        ),
    )

    run_cfg = CrawlerRunConfig(
        cache_mode=CacheMode.ENABLED,
        page_timeout=4 * 60 * 1000,
        # magic=True,
        # simulate_user=True,
        # override_navigator=True,
        # process_iframes=True,
        # wait_for="js:() => document.readyState === 'complete'",
        scan_full_page=True,
        scroll_delay=1,
        delay_before_return_html=20,
        # js_code=[
        #     "window.scrollTo(0, document.body.scrollHeight)",
        #     "new Promise(resolve => requestAnimationFrame(resolve))",
        #     "(function() { return new Promise(resolve => setTimeout(resolve, 5000)); })();",
        # ],
        # verbose=True,
        remove_overlay_elements=True,
        scraping_strategy=LXMLWebScrapingStrategy(),
    )

    html_cfg = CrawlerRunConfig(
        scraping_strategy=LXMLWebScrapingStrategy(),
        verbose=False,
    )

    # Instantiate Firesolverr client and session
    flaresolverr_client = AsyncFlaresolverrClient(
        flaresolverr_url="http://localhost:8191/v1"
    )

    # LLM setup
    litellm.api_key = os.getenv(
        "LITELLM_API_KEY",
        "cpk_124e1b76efc446f99bbc7041356768c4.60f6fe94168451c08dcd92b124e6b532.sebtU7pEmnZfMPyCq07NidXRaK5gQWn9",
    )

    llm_markdown_route = "chutes"

    if llm_markdown_route == "copilot":
        litellm.api_base = "http://localhost:4141/"
        client = instructor.from_litellm(acompletion, mode=instructor.Mode.TOOLS)
        model_name = "openai/claude-sonnet-4"
    elif llm_markdown_route == "chutes":
        litellm.api_base = "https://api.chutes.ai/v1/"
        client = instructor.from_litellm(acompletion, mode=instructor.Mode.JSON)
        # Using Llama models is causing JSON validation errors so using Deepseek models, R1 preferred over V3
        model_name = "openai/chutesai/Llama-4-Maverick-17B-128E-Instruct-FP8"

    # Rate limiting for LLM calls
    LLM_CALLS = int(os.getenv("LLM_CALLS_PER_PERIOD", "1"))
    LLM_CALLS_PERIOD = int(os.getenv("LLM_PERIOD_SECONDS", "3"))
    llm_call_limiter = AsyncLimiter(LLM_CALLS, LLM_CALLS_PERIOD)

    # Create outputs directory for debugging
    outputs_dir = os.path.join(os.path.dirname(__file__), "outputs")
    os.makedirs(outputs_dir, exist_ok=True)

    # Create output file with timestamp and model name for debugging
    model_for_filename = model_name.split("/")[-1].replace("-", "_").lower()
    output_file = os.path.join(
        outputs_dir,
        f"events_{datetime.now().strftime('%Y-%m-%d_%H-%M')}_{model_for_filename}.json",
    )
    # Track URLs and results
    processed_urls = set()
    results = {}

    # async with crawler_semaphore:
    async with AsyncWebCrawler(config=browser_cfg) as crawler:
        # First pass: Process initial URLs in bulk
        urls_to_process = []
        for url in urls:
            if url not in processed_urls and not is_blacklisted(url):
                processed_urls.add(url)
                urls_to_process.append(url)
            elif is_blacklisted(url):
                logger.info(f"Skipping blacklisted URL: {url}")
                processed_urls.add(url)

        # Process the initial URLs in bulk
        if urls_to_process:
            first_pass_results = await crawl_and_process_url_many(
                urls_to_process,
                crawler,
                run_cfg,
                flaresolverr_client,
                html_cfg,
                dispatcher,
                model_name,
                llm_call_limiter,
                client,
                use_links_model=True,
            )

            # Extract additional links from results
            additional_urls = []
            for result in first_pass_results:
                url = result["url"]
                results[url] = {k: v for k, v in result.items() if k != "url"}

                # Extract additional links if the result was successful
                if result.get("success") and "event_details" in result:
                    event_details = result["event_details"]
                    if event_details.get("is_event", False):
                        for link in event_details.get("additional_links", []):
                            if (
                                link
                                and link not in processed_urls
                                and not is_blacklisted(link)
                            ):
                                processed_urls.add(link)
                                logger.info(
                                    f"Adding additional link for processing: {link}"
                                )
                                additional_urls.append(link)
                            elif link and is_blacklisted(link):
                                logger.info(
                                    f"Skipping blacklisted additional link: {link}"
                                )
                                processed_urls.add(link)

            # Process additional links in bulk
            if additional_urls:
                logger.info(f"Processing {len(additional_urls)} additional links")
                additional_results = await crawl_and_process_url_many(
                    additional_urls,
                    crawler,
                    run_cfg,
                    flaresolverr_client,
                    html_cfg,
                    dispatcher,
                    model_name,
                    llm_call_limiter,
                    client,
                    use_links_model=False,
                )

                # Add results from additional links
                for result in additional_results:
                    url = result["url"]
                    results[url] = {k: v for k, v in result.items() if k != "url"}

    # Save results to a file for debugging
    try:
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        logger.info(f"Results saved to {os.path.abspath(output_file)}")
    except Exception as e:
        logger.error(f"Error writing results to file: {str(e)}")

    return results
