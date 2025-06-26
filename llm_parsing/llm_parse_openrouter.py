# %% Imports
import asyncio
import json
import logging
import os
import re
import sys
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple, Type, TypeVar, Union
from urllib.parse import quote_plus

import aiohttp
import httpx
import instructor
import tenacity

# import nest_asyncio
from config_llm2 import (  # Ensure these are correctly imported/defined in your config
    JINA_BASE_URL,
    OPENROUTER_API_KEYS,
    URL_CACHE,
)
from dotenv import load_dotenv
from openai import AsyncOpenAI
from openai import RateLimitError as OpenAIRateLimitError  # Import openai's error
from openai._exceptions import APIStatusError  # Import generic status error
from pydantic import BaseModel, Field
from tenacity import (
    RetryCallState,
    before_sleep_log,
    retry,
    retry_if_exception,
    stop_after_attempt,
)

# %% Setup Logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# %% Environment and Constants
load_dotenv()
JINA_API_KEY = os.getenv("JINA_API_KEY")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
# Ensure OPENROUTER_API_KEYS is loaded correctly as a list
if not isinstance(OPENROUTER_API_KEYS, list) or not OPENROUTER_API_KEYS:
    raise ValueError("OPENROUTER_API_KEYS must be a non-empty list in config_llm.py")

# %% HTTPX Client (Keep as is)
TIMEOUT_CONFIG = httpx.Timeout(10.0, read=180.0)
HTTPX_CLIENT = httpx.AsyncClient(timeout=TIMEOUT_CONFIG)


# %% get_link_markdown (Keep as is, added logging)
async def get_link_markdown(url: str) -> Optional[str]:
    """Convert URL content to markdown using Jina API via httpx."""
    if url in URL_CACHE:
        # logger.debug(f"Cache hit for URL: {url}")
        return URL_CACHE[url]

    # logger.debug(f"Fetching markdown for URL: {url}")
    try:
        encoded_url = quote_plus(url)
        headers = {
            "Authorization": f"Bearer {JINA_API_KEY}",
            "Accept": "text/markdown",
        }
        start_time = time.time()
        response = await HTTPX_CLIENT.get(
            f"{JINA_BASE_URL}{encoded_url}", headers=headers
        )
        elapsed_time = time.time() - start_time
        logger.info(f"Jina API response in {elapsed_time:.2f} seconds")

        if response.status_code == 200:
            content = response.text
            URL_CACHE[url] = content
            return content
        else:
            error_detail = response.text[:200] if response.text else "No details"
            logger.error(
                f"Error fetching URL {url}: Status {response.status_code} - {error_detail}"
            )
            response.raise_for_status()  # Raise for non-2xx

    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP error processing URL {url}: {e}")
        URL_CACHE[url] = None
        return None
    except httpx.RequestError as e:
        logger.error(f"Request error processing URL {url}: {e}")
        URL_CACHE[url] = None
        return None
    except Exception as e:
        logger.error(f"Unexpected error processing URL {url}: {str(e)}")
        URL_CACHE[url] = None
        return None


async def close_httpx_client():
    await HTTPX_CLIENT.aclose()


# %% Pydantic Models (Keep as is)
class NobleTruth(BaseModel):
    no: int = Field(..., description="The number of the Noble Truth")
    truth_name: str = Field(..., description="The name of the Noble Truth")
    detailed_description: str = Field(
        ..., description="A detailed description of the Noble Truth"
    )


class ImageDescription(BaseModel):
    detailed_description: str = Field(
        ..., description="A detailed description of the image"
    )


class IntroMessage(BaseModel):
    is_friendly: bool


T = TypeVar("T", bound=BaseModel)


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
    return 0.1


# %% Main Function using Tenacity
async def instructor_chat_completion(
    model: str,
    response_model: Union[Type[T], List[Type[T]]],
    content: str,
    image_urls: Optional[List[str]] = None,
    system_prompt: Optional[str] = None,
    tool_mode: instructor.Mode = instructor.Mode.JSON,
    max_retries: int = 5,  # Use max_retries for stop condition
) -> T:
    """
    A wrapper function for instructor chat completion with robust retry handling.

    Automatically handles rate limiting with appropriate retries (specific delay or
    key rotation) based on error details.

    Args:
        model: The model identifier string
        response_model: Pydantic model(s) for structured response
        content: The text content for the request
        image_urls: Optional list of image URLs to include
        system_prompt: Optional system prompt
        tool_mode: The instructor tool mode
        max_retries: Maximum number of retry attempts (per key effectively)

    Returns:
        Structured response as the specified Pydantic model
    """
    # Shared state across retries
    current_key_index = 0
    keys_tried_in_current_attempt: Set[int] = set()  # Track keys per attempt sequence
    total_keys = len(OPENROUTER_API_KEYS)

    # Pre-build messages (static part of request)
    messages = [{"role": "system", "content": system_prompt}] if system_prompt else []
    user_content_parts = [{"type": "text", "text": content}]
    if image_urls:
        user_content_parts.extend(
            {"type": "image_url", "image_url": {"url": url}} for url in image_urls
        )
    messages.append({"role": "user", "content": user_content_parts})

    # Provider-specific options
    extra_body = (
        {"provider": {"require_parameters": True}}
        if tool_mode != instructor.Mode.JSON
        else {}
    )

    @retry(
        retry=retry_if_exception(is_rate_limit_error),
        wait=custom_wait,  # Use the updated custom wait logic
        stop=stop_after_attempt(
            max_retries * total_keys + 1
        ),  # Allow retries across all keys
        before_sleep=before_sleep_log(logger, logging.INFO),
        reraise=True,
    )
    async def _execute_with_retry():
        nonlocal current_key_index, keys_tried_in_current_attempt

        # Check if we've exhausted all keys in this attempt cycle
        if len(keys_tried_in_current_attempt) >= total_keys:
            logger.error(
                "All API keys have been tried and failed within retry attempts. Raising."
            )
            raise tenacity.TryAgain("Exhausted all API keys during retry attempts.")

        # Get current API key for this attempt
        api_key = OPENROUTER_API_KEYS[current_key_index]
        keys_tried_in_current_attempt.add(current_key_index)

        # logger.info(f"Attempting API call with key index {current_key_index}")

        # Create client with current key
        client = instructor.patch(
            AsyncOpenAI(
                base_url="https://openrouter.ai/api/v1",
                api_key=api_key,
                max_retries=0,  # Disable client's built-in retries, use tenacity
            ),
            mode=tool_mode,
        )

        try:
            start_time = time.time()
            response = await client.chat.completions.create(
                model=model,
                messages=messages,
                response_model=response_model,
                extra_body=extra_body if extra_body else None,
            )
            elapsed_time = time.time() - start_time
            logger.info(f"Response time: {elapsed_time:.2f}s")
            keys_tried_in_current_attempt.clear()  # Reset tried keys on success
            return response

        except Exception as e:
            # Check if this is a rate limit error in any format
            if is_rate_limit_error(e):
                logger.warning(
                    f"Rate limit error detected with key index {current_key_index}"
                )
                _handle_rate_limit(e)
                # Re-raise for tenacity to handle retry/wait based on custom_wait
                raise e
            else:
                # Not a rate limit error
                logger.error(
                    f"Non-rate-limit error during API call with key index {current_key_index}: {e}"
                )
                keys_tried_in_current_attempt.clear()  # Reset on non-retryable error
                raise  # Re-raise other errors

    def _handle_rate_limit(e):
        """Handle rate limit errors by determining whether to wait or rotate keys."""
        nonlocal current_key_index

        # Decide action based on parsed delay
        delay_needed = extract_retry_seconds(e)

        if delay_needed is None:
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
        else:
            # Specific delay found, tenacity's `custom_wait` will handle the sleep
            logger.info(
                f"Rate limit requires specific delay. Waiting {delay_needed:.2f}s before next attempt (handled by tenacity)."
            )
            # Key index does not change here, will retry with the same key after delay

    # Execute with retries
    try:
        return await _execute_with_retry()
    except tenacity.RetryError as e:
        logger.error(
            f"API call failed after multiple retries ({max_retries * total_keys + 1} attempts): {e}"
        )
        raise  # Re-raise the final RetryError
