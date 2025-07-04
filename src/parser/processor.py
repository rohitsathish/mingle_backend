"""Message processing module for extracting events from WhatsApp messages.

Handles processing of WhatsApp message files including image analysis,
URL extraction, and event extraction using LLM models.
"""

import asyncio
import json
import os
import platform
import re
import shutil
import sys
import winsound
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple, Union
from urllib.parse import urlparse, urlunparse

import tiktoken
import tldextract
import validators
from aiolimiter import AsyncLimiter
from config.config import MESSAGES_DIR, PARSED_EVENTS_DIR
from config.logs import get_logger
from src.parser.info.models import (
    MODELS,
    WORKING_FILE_SUFFIX,
    get_model_for_task,
    get_model_config,
    get_models_for_event_extraction,
)
from src.parser.info.llm_prompts import SYSTEM_PROMPT, EventResponse, ImageDescription
from src.parser.api import (
    close_httpx_client,
    instructor_chat_completion,
)
from src.parser.crawl4ai import crawl_and_extract_event_details_from_urls
from src.parser.utils import is_blacklisted
from urlextract import URLExtract

# Configure logging using centralized config
# Use proper module name even when run as __main__
module_name = __name__ if __name__ != "__main__" else "src.llm.processor"
logger = get_logger(module_name)

# URL extractor instance
url_extractor = URLExtract()

# Semaphore for limiting concurrency
MAX_CONCURRENT_TASKS = 5


async def limited_process_with_progress(
    tasks,
    description="Processing",
    rate_limit=None,
    period=1.0,
    concurrency_limit=MAX_CONCURRENT_TASKS,
):
    """Process async tasks with progress tracking and concurrency limit."""
    total = len(tasks)
    if not total:
        logger.info(f"No tasks to process for: {description}")
        return []

    # Set up rate limiter if specified
    rate_limiter = None
    if rate_limit is not None:
        try:
            rate_limiter = AsyncLimiter(rate_limit, period)
            logger.info(f"Rate limiting enabled: {rate_limit} requests per {period}s")
        except ImportError:
            logger.warning("aiolimiter package not found. Rate limiting disabled.")

    logger.info(
        f"{description} ({total} items with {concurrency_limit} max concurrent tasks)..."
    )

    semaphore = asyncio.Semaphore(concurrency_limit)
    completed = 0
    results = [None] * total

    async def run_with_semaphore(task, index):
        async with semaphore:
            # Apply rate limiting if configured
            if rate_limiter is not None:
                async with rate_limiter:
                    try:
                        result = await task
                        return index, result
                    except Exception as e:
                        raise e
            else:
                try:
                    result = await task
                    return index, result
                except Exception as e:
                    raise e

    # Start all tasks but limit concurrency with semaphore
    pending_tasks = [
        asyncio.create_task(run_with_semaphore(task, i)) for i, task in enumerate(tasks)
    ]

    for future in asyncio.as_completed(pending_tasks):
        index, result = await future
        results[index] = result
        completed += 1

        if completed % max(1, total // 10) == 0 or completed == total:
            logger.info(f"Progress: {completed}/{total} ({int(completed/total*100)}%)")

    logger.info(f"Completed: {completed}/{total} ({int(completed/total*100)}%)")
    return results


def create_working_file(original_filename: str, reload: bool = False) -> Dict[str, Any]:
    """Create or load a working copy of a message JSON file."""
    if not original_filename.endswith(".json"):
        raise ValueError("Filename must end with .json")

    base_name = original_filename[:-5]
    working_filename = f"{base_name}{WORKING_FILE_SUFFIX}.json"
    original_filepath = os.path.join(MESSAGES_DIR, original_filename)
    working_filepath = os.path.join(MESSAGES_DIR, working_filename)

    # Delete existing working file if reload requested
    if reload and os.path.exists(working_filepath):
        os.remove(working_filepath)

    # Return existing working file if available
    if os.path.exists(working_filepath):
        logger.info(f"Using existing working file: {working_filename}")
        with open(working_filepath, "r", encoding="utf-8") as f:
            return json.load(f)

    # Create new working file
    if not os.path.exists(original_filepath):
        logger.error(f"Original file not found: {original_filepath}")
        raise FileNotFoundError(f"Original file not found: {original_filepath}")

    try:
        shutil.copy2(original_filepath, working_filepath)
        with open(working_filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        if os.path.exists(working_filepath):
            os.remove(working_filepath)
        raise


def estimate_tokens(text: str) -> int:
    """Estimate the number of tokens in a text string."""
    try:
        encoding = tiktoken.get_encoding("o200k_base")
        return len(encoding.encode(text))
    except Exception:
        # Fallback approximation: 4 characters ≈ 1 token
        return len(text) // 4


def create_message_chunks(
    data: Dict[str, Any],
    system_prompt: str = SYSTEM_PROMPT,
    token_limit: int = None,
    chunk_num: int = None,
) -> List[Dict[str, Any]]:
    """Split messages JSON into chunks based on token limit or desired chunk count."""
    logger.info("Creating message chunks for processing")

    # Calculate system prompt token count
    prompt_tokens = estimate_tokens(system_prompt)

    # Calculate token counts for each group
    groups_with_tokens = []
    for i, group in enumerate(data.get("whatsapp_groups", [])):
        group_tokens = 0
        group_name = group.get("group_name", "Unknown Group")
        group_tokens += (
            estimate_tokens(group_name) * 2
        )  # Count twice for formatting overhead

        for msg_key, msg_list in group.get("messages", {}).items():
            for msg in msg_list:
                if isinstance(msg, dict) and "text" in msg:
                    msg_text = f"From {group_name} at {msg_key}: {msg.get('text', '')}"
                    group_tokens += estimate_tokens(msg_text)

        groups_with_tokens.append({"index": i, "group": group, "tokens": group_tokens})

    total_group_tokens = sum(g["tokens"] for g in groups_with_tokens)
    if total_group_tokens == 0:
        raise ValueError("No tokens found in groups")

    chunks = []

    # Case 1: Create a specific number of chunks
    if chunk_num is not None and chunk_num > 0:
        groups_with_tokens.sort(key=lambda g: g["tokens"], reverse=True)

        # Initialize chunks
        for _ in range(chunk_num):
            chunks.append(
                {
                    "created_at": data.get("created_at", ""),
                    "whatsapp_groups": [],
                    "_token_count": prompt_tokens,
                }
            )

        # Distribute groups to chunks using greedy approach
        for group_data in groups_with_tokens:
            min_tokens_chunk = min(chunks, key=lambda c: c["_token_count"])
            min_tokens_chunk["whatsapp_groups"].append(group_data["group"])
            min_tokens_chunk["_token_count"] += group_data["tokens"]

    # Case 2: Create chunks based on token limit
    else:
        if token_limit is None:
            raise ValueError(
                "token_limit must be specified if chunk_num is not provided"
            )

        groups_with_tokens.sort(key=lambda g: g["tokens"])
        current_chunk = {
            "created_at": data.get("created_at", ""),
            "whatsapp_groups": [],
            "_token_count": prompt_tokens,
        }

        for group_data in groups_with_tokens:
            if current_chunk["_token_count"] + group_data["tokens"] > token_limit:
                if current_chunk["whatsapp_groups"]:
                    chunks.append(current_chunk)
                current_chunk = {
                    "created_at": data.get("created_at", ""),
                    "whatsapp_groups": [group_data["group"]],
                    "_token_count": prompt_tokens + group_data["tokens"],
                }
            else:
                current_chunk["whatsapp_groups"].append(group_data["group"])
                current_chunk["_token_count"] += group_data["tokens"]

        if current_chunk["whatsapp_groups"]:
            chunks.append(current_chunk)

    # Clean up temporary token count field and log stats
    chunk_stats = []
    for i, chunk in enumerate(chunks):
        token_count = chunk.pop("_token_count")
        group_names = [g.get("group_name", "Unknown") for g in chunk["whatsapp_groups"]]
        chunk_stats.append(
            f"Chunk {i+1}: {len(chunk['whatsapp_groups'])} groups, ~{token_count} tokens. Groups: {group_names}"
        )

    logger.info(
        f"Created {len(chunks)} chunks from {len(data.get('whatsapp_groups', []))} groups"
    )
    for stat in chunk_stats:
        logger.info(stat)

    return chunks


class MessagesProcessor:
    """Main class for processing WhatsApp messages and extracting events."""

    def __init__(self, filepath: str = None, data: Dict[str, Any] = None):
        """Initialize with either a filepath or data dictionary."""
        self.filepath = filepath
        self.data = data
        self.source_json_name = None

        if self.filepath:
            with open(self.filepath, "r", encoding="utf-8") as f:
                self.data = json.load(f)
            self.source_json_name = os.path.basename(filepath).replace(
                WORKING_FILE_SUFFIX, ""
            )

    async def process_images(self) -> None:
        """Process and enrich messages with image descriptions."""
        logger.info("Processing images")

        # Collect image coroutines
        coroutines = []
        image_locations = {}
        model_key = get_model_for_task("image_analysis")
        model_config = get_model_config(model_key)

        for group_index, group in enumerate(self.data.get("whatsapp_groups", [])):
            for msg_key, msg_list in group.get("messages", {}).items():
                for msg_part_index, msg_part in enumerate(msg_list):
                    images = msg_part.get("imgs", {})
                    if not images:
                        continue

                    for img_key, base64_img in images.items():
                        if not base64_img or not base64_img.startswith("data:image"):
                            continue

                        unique_id = (
                            f"{group_index}-{msg_key}-{msg_part_index}-{img_key}"
                        )
                        image_locations[unique_id] = (
                            group_index,
                            msg_key,
                            msg_part_index,
                            img_key,
                        )
                        coroutines.append(
                            instructor_chat_completion(
                                model=model_config["name"],
                                response_model=ImageDescription,
                                content="Is this image related to a potential event announcement? If so, carefully and comprehensively capture all event details and information. Convey them verbosely.",
                                image_urls=[base64_img],
                                tool_mode=model_config.get("tool_mode", "tools"),
                                route=model_config["route"],
                                reasoning=model_config.get("reasoning"),
                                model_key=model_key,
                            )
                        )

        if not coroutines:
            logger.info("No images found to process")
            return

        # Process images with progress tracking
        results = await limited_process_with_progress(
            coroutines, "Processing images", 12, 1
        )

        # Update data with results
        processed_count = error_count = 0
        unique_ids = list(image_locations.keys())

        for i, result in enumerate(results):
            if isinstance(result, Exception):
                error_count += 1
                logger.error(
                    f"Error processing image {i+1}/{len(results)}: {str(result)}"
                )
                continue

            if not isinstance(result, ImageDescription):
                error_count += 1
                logger.error(f"Unexpected result type for image {i+1}/{len(results)}")
                continue

            if result.is_event_related and result.event_description:
                group_index, msg_key, msg_part_index, img_key = image_locations[
                    unique_ids[i]
                ]
                msg_part = self.data["whatsapp_groups"][group_index]["messages"][
                    msg_key
                ][msg_part_index]

                # Add description to message text
                description = result.event_description
                prefix = f"[Details from image {img_key}]: {description}"
                existing_text = msg_part.get("text", "")
                separator = "\n" if existing_text else ""
                msg_part["text"] = existing_text + separator + prefix
                processed_count += 1

        # Critical error - if we couldn't process any images successfully and had errors
        if error_count > 0 and processed_count == 0:
            raise RuntimeError(
                f"Critical failure: All {error_count} image processing attempts failed"
            )

        logger.info(f"Added {processed_count} image descriptions to messages")

        # Remove all image data to save space
        removed_count = 0
        for group in self.data.get("whatsapp_groups", []):
            for msg_list in group.get("messages", {}).values():
                for msg_part in msg_list:
                    if isinstance(msg_part, dict) and "imgs" in msg_part:
                        del msg_part["imgs"]
                        removed_count += 1

        logger.info(f"Removed 'imgs' key from {removed_count} message parts")

        # Save updated data if we have a filepath
        if self.filepath:
            with open(self.filepath, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2, ensure_ascii=False)

    async def process_links(self) -> None:
        """Extract URLs, fetch content using Crawl4AI and LLM, and update messages."""
        logger.info("Processing URLs using Crawl4AI and LLM")

        # Extract URLs from messages
        url_locations = {}
        unique_urls = set()

        def preprocess_text_for_url_extraction(text: str) -> str:
            """Preprocess text to improve URL extraction by adding spaces before URLs."""
            if not text:
                return text

            # Pattern to match URLs that are immediately preceded by text (no space)
            # Only match patterns that clearly indicate concatenated URLs, not legitimate domain parts
            url_patterns = [
                r"(\w)(https?://)",  # word followed by http/https
                r"(\w)(www\.)",  # word followed by www.
                r"(\w)(ftp://)",  # word followed by ftp
                # Note: Removed TLD patterns as they can break legitimate URLs like bookmyshow.com
                # The URLExtract library is robust enough to handle URLs without this preprocessing
            ]

            processed_text = text
            for pattern in url_patterns:
                # Insert space between word and URL starter
                processed_text = re.sub(pattern, r"\1 \2", processed_text)

            return processed_text

        def normalize_url(url: str) -> str:
            """Normalize URL by adding scheme/TLD if missing and validating."""
            if not url:
                return url

            original_url = url.strip()

            # Remove common prefixes that aren't part of the URL
            url = re.sub(
                r"^(url:|link:|visit:|check out:)\s*",
                "",
                original_url,
                flags=re.IGNORECASE,
            )

            # Add scheme if missing
            if not url.startswith(("http://", "https://", "ftp://")):
                url = f"https://{url}"

            # Parse original URL structure to preserve path/query/fragment
            parsed = urlparse(url)

            # Extract domain components using tldextract
            extracted = tldextract.extract(url)

            # Build normalized domain based on tldextract results
            normalized_domain = None

            if extracted.domain and extracted.suffix:
                # Standard case: valid domain and TLD found
                parts = [
                    p
                    for p in [extracted.subdomain, extracted.domain, extracted.suffix]
                    if p
                ]
                normalized_domain = ".".join(parts)

            elif extracted.domain and not extracted.suffix:
                # Handle IP addresses, localhost, or missing TLD cases
                if validators.url(url):  # IP or localhost - use as-is
                    return url

                # Try common TLD fallbacks for domain without valid suffix
                for tld in ["com", "org", "net"]:
                    test_domain = f"{extracted.domain}.{tld}"
                    test_url = urlunparse(
                        (
                            parsed.scheme,
                            test_domain,
                            parsed.path,
                            parsed.params,
                            parsed.query,
                            parsed.fragment,
                        )
                    )
                    if validators.url(test_url):
                        return test_url

            elif extracted.subdomain and not extracted.domain and not extracted.suffix:
                # Edge case: only subdomain found (malformed input)
                for tld in ["com", "org", "net"]:
                    test_domain = f"{extracted.subdomain}.{tld}"
                    test_url = urlunparse(
                        (
                            parsed.scheme,
                            test_domain,
                            parsed.path,
                            parsed.params,
                            parsed.query,
                            parsed.fragment,
                        )
                    )
                    if validators.url(test_url):
                        return test_url

            # Reconstruct URL with normalized domain
            if normalized_domain:
                normalized_url = urlunparse(
                    (
                        parsed.scheme,
                        normalized_domain,
                        parsed.path,
                        parsed.params,
                        parsed.query,
                        parsed.fragment,
                    )
                )

                if validators.url(normalized_url):
                    return normalized_url

                # Try HTTP fallback for HTTPS failures
                if normalized_url.startswith("https://"):
                    http_url = normalized_url.replace("https://", "http://", 1)
                    if validators.url(http_url):
                        return http_url

            # Return original if all normalization attempts fail
            return original_url

        # The main URL extraction code:
        for group_index, group in enumerate(self.data.get("whatsapp_groups", [])):
            for msg_key, msg_list in group.get("messages", {}).items():
                for msg_part_index, msg_part in enumerate(msg_list):
                    if not isinstance(msg_part, dict) or "text" not in msg_part:
                        continue

                    text = msg_part.get("text", "")
                    if not text:
                        continue

                    # Preprocess text to add spaces before URLs
                    preprocessed_text = preprocess_text_for_url_extraction(text)

                    # Extract URLs from preprocessed text
                    found_urls = url_extractor.find_urls(preprocessed_text)
                    location = (group_index, msg_key, msg_part_index)

                    for url in found_urls:
                        # Normalize the URL (add protocol if missing, validate)
                        normalized_url = normalize_url(url.rstrip("/"))

                        # Only add if it's a valid URL after normalization
                        if normalized_url and validators.url(normalized_url):
                            unique_urls.add(normalized_url)

                            if normalized_url not in url_locations:
                                url_locations[normalized_url] = []
                            if location not in url_locations[normalized_url]:
                                url_locations[normalized_url].append(location)

        # Filter URLs to remove blacklisted ones
        filtered_urls = {url for url in unique_urls if not is_blacklisted(url)}
        logger.info(f"Found {len(filtered_urls)} URLs to process after filtering.")

        if not filtered_urls:
            logger.info("No URLs to process")
            return

        # Get model for HTML parsing
        html_model_key = get_model_for_task("html_parsing")
        logger.info(f"Using model {html_model_key} for HTML parsing")

        # Process URLs using Crawl4AI and LLM
        logger.info(f"Starting URL processing")

        try:
            results = await crawl_and_extract_event_details_from_urls(
                list(filtered_urls), html_model_key
            )

            # Check if we have any successful results
            successful_urls = [
                url for url, data in results.items() if data.get("success")
            ]
            failed_urls = [
                url for url, data in results.items() if not data.get("success")
            ]

            logger.info(
                f"URL processing results: {len(successful_urls)} successful, {len(failed_urls)} failed"
            )

            if not successful_urls:
                logger.warning(
                    "No URLs were successfully processed, but continuing to save working file"
                )
            else:
                logger.info(
                    f"Successfully processed {len(successful_urls)} URLs using Crawl4AI and LLM"
                )

                # Update data with event details
                appended = 0

                for url, locations in url_locations.items():
                    if url not in results:
                        logger.debug(f"URL {url} not found in results, skipping")
                        continue

                    result_data = results[url]

                    if not result_data.get("success"):
                        logger.warning(
                            f"Processing failed for URL: {url}, error: {result_data.get('error_details', 'Unknown error')}"
                        )
                        continue

                    event_details = result_data.get("event_details", {})

                    # Build structured content to add to the message
                    content_lines = []

                    if event_details.get("is_event"):
                        content_lines.append(
                            f"{event_details.get('description', 'No description available')}"
                        )

                        # Add information about additional links if they exist and were processed
                        # Filter out additional links that are the same as the current URL to avoid duplication
                        additional_links = [
                            link for link in event_details.get("additional_links", [])
                            if link != url  # Exclude self-references
                        ]

                        if additional_links:
                            content_lines.append("RELATED LINKS:")

                            for add_link in additional_links:
                                if add_link in results and results[add_link].get(
                                    "success"
                                ):
                                    add_link_details = results[add_link].get(
                                        "event_details", {}
                                    )
                                    if add_link_details.get("is_event"):
                                        content_lines.append(
                                            f"INFO FROM ADDITIONAL LINK: {add_link} \n {add_link_details.get('description', 'No description available')}"
                                        )
                    else:
                        content_lines.append(f"URL: {url} - NOT AN EVENT RELATED LINK")

                    # Combine all content lines
                    content = "\n".join(content_lines)

                    # Add content to each message that contained this URL
                    for location in locations:
                        try:
                            group_index, msg_key, msg_part_index = location
                            msg_part = self.data["whatsapp_groups"][group_index][
                                "messages"
                            ][msg_key][msg_part_index]

                            # Initialize text field if missing
                            if "text" not in msg_part:
                                msg_part["text"] = ""

                            # Add structured content
                            prefix = f"\n[Content from URL {url}]:\n{content}\n"

                            # Avoid adding duplicate content
                            if prefix not in msg_part["text"]:
                                msg_part["text"] += prefix
                                appended += 1

                        except (KeyError, IndexError, TypeError) as e:
                            logger.error(
                                f"Error updating message with URL content: {str(e)}"
                            )

                logger.info(
                    f"Added content for {len(successful_urls)} URLs across {appended} message locations"
                )

        except Exception as e:
            logger.error(f"Critical error in URL processing: {str(e)}", exc_info=True)
            logger.error(
                f"URL processing failed completely, but continuing to save working file"
            )

        # Save updated data if we have a filepath
        if self.filepath:
            with open(self.filepath, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2, ensure_ascii=False)

    async def extract_events(self) -> Optional[Dict[str, Any]]:
        """Extract events from messages using task-based model selection."""
        logger.info("Extracting events from messages")

        output_dir = str(PARSED_EVENTS_DIR)

        # Get model configurations for event extraction (automatically uses multiple if configured)
        model_keys = get_models_for_event_extraction()

        model_configs = []
        for model_key in model_keys:
            model_config = get_model_config(model_key)
            model_name = model_config["name"]
            token_limit = int(model_config.get("input_tokens", 1e5))
            model_route = model_config["route"]
            model_tool_mode = model_config.get("tool_mode", "json")
            model_reasoning = model_config.get("reasoning")
            model_configs.append(
                (model_key, model_name, token_limit, model_route, model_tool_mode, model_reasoning)
            )
            logger.info(f"Using model {model_key} ({model_name}) for event extraction")

        # Process each model
        if len(model_configs) > 1:
            # Multiple models - process in parallel
            model_tasks = [
                self._process_model(
                    model_key, model_name, token_limit, model_route, model_tool_mode, model_reasoning, output_dir
                )
                for model_key, model_name, token_limit, model_route, model_tool_mode, model_reasoning in model_configs
            ]

            # Execute all model processing tasks with progress tracking
            logger.info(f"Processing {len(model_tasks)} models in parallel")
            results = await limited_process_with_progress(
                model_tasks, "Processing models"
            )

            # Filter out None results
            all_results = [result for result in results if result is not None]
            logger.info(
                f"Successfully processed {len(all_results)}/{len(model_configs)} models"
            )

            return None  # In multiple model mode, results are saved to files
        else:
            # Single model - process directly
            model_key, model_name, token_limit, model_route, model_tool_mode, model_reasoning = model_configs[0]
            logger.info(f"Processing with single model: {model_name}")

            return await self._process_model(
                model_key, model_name, token_limit, model_route, model_tool_mode, model_reasoning, output_dir
            )

    async def _process_model(
        self,
        model_key: str,
        model_name: str,
        token_limit: int,
        model_route: str,
        model_tool_mode: str,
        model_reasoning: Optional[str],
        output_dir: str,
    ) -> Optional[Dict[str, Any]]:
        """Process messages with a specific model."""

        # Create chunks based on token limit
        chunks = create_message_chunks(
            self.data, SYSTEM_PROMPT, token_limit=token_limit
        )

        # Process all chunks for this model in parallel  
        chunk_tasks = [
            self._process_chunk(
                chunk, model_key, model_name, model_route, model_tool_mode, model_reasoning, i, len(chunks)
            )
            for i, chunk in enumerate(chunks)
        ]

        # Execute all chunk processing tasks with progress tracking
        logger.info(f"Processing {len(chunk_tasks)} chunks with model {model_name}")
        chunk_results = await limited_process_with_progress(
            chunk_tasks, f"Processing chunks with {model_name}"
        )

        # Filter out None results
        chunk_results = [result for result in chunk_results if result is not None]

        # Combine results from all chunks
        combined_result = self._combine_responses(chunk_results)

        # Save results if we have multiple models
        self._save_results(combined_result, model_name, output_dir)

        return combined_result

    async def _process_chunk(
        self,
        chunk: Dict[str, Any],
        model_key: str,
        model: str,
        model_route: str,
        model_tool_mode: str,
        model_reasoning: Optional[str],
        chunk_index: int,
        total_chunks: int,
    ) -> Optional[Dict[str, Any]]:
        """Process a single message chunk with a specific model."""
        # Create simplified message list for this chunk
        chunk_messages = []
        for group in chunk.get("whatsapp_groups", []):
            group_name = group.get("group_name", "Unknown Group")
            for msg_date, msg_list in group.get("messages", {}).items():
                for msg in msg_list:
                    if not isinstance(msg, dict) or not msg.get("text"):
                        continue

                    message_entry = {
                        "group_name": group_name,
                        "date": msg_date,
                        "text": msg.get("text", "").strip(),
                    }

                    if message_entry["text"]:
                        chunk_messages.append(message_entry)

        # Skip empty chunks
        if not chunk_messages:
            logger.warning(
                f"Chunk {chunk_index+1}/{total_chunks} has no messages, skipping"
            )
            return None

        # Create formatted message content
        content = f"Messages to analyze for events (chunk {chunk_index+1}/{total_chunks}):\n\n"
        for j, msg in enumerate(chunk_messages, 1):
            content += f"Message {j} from {msg['group_name']} on {msg['date']}:\n{msg['text']}\n\n"

        try:
            logger.info(
                f"Processing chunk with model details: {model}, {model_route}, {model_tool_mode}"
            )
            # Process this chunk with LLM
            response = await instructor_chat_completion(
                model=model,
                response_model=EventResponse,
                content=content,
                system_prompt=SYSTEM_PROMPT,
                tool_mode=model_tool_mode,
                route=model_route,
                reasoning=model_reasoning,
                model_key=model_key,
            )

            chunk_result = {
                "events": [event.model_dump() for event in response.events],
                "new_categories": list(response.new_categories),
            }

            logger.info(
                f"Extracted {len(response.events)} events from chunk {chunk_index+1}/{total_chunks}"
            )
            return chunk_result

        except Exception as e:
            logger.error(f"Error processing chunk {chunk_index+1}/{total_chunks}: {e}")
            return None

    def _combine_responses(self, responses: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Combine multiple chunk responses into a single response."""
        if not responses:
            return {"events": [], "new_categories": []}

        combined_events = []
        combined_categories = set()

        for response in responses:
            if not response:
                continue

            # Add all events
            combined_events.extend(response.get("events", []))

            # Add all new categories
            new_categories = response.get("new_categories", [])
            if new_categories:
                combined_categories.update(new_categories)

        # Sort events by start_date if available
        combined_events.sort(
            key=lambda e: e.get("start_date", "9999-99-99"), reverse=False
        )

        return {
            "events": combined_events,
            "new_categories": list(combined_categories),
        }

    def _save_results(
        self, result: Dict[str, Any], model_name: str, output_dir: str
    ) -> None:
        """Save results to a file with appropriate naming."""
        # Add source information to the result
        source_created_at = self.data.get("created_at", "")

        # Add source information to each event
        for event in result["events"]:
            event["source_json_name"] = self.source_json_name
            event["source_created_at"] = source_created_at

        # Determine output filename
        sanitized_model_name = (
            model_name.split("/")[-1] if "/" in model_name else model_name
        )
        logger.info(f"Sanitized model name: {sanitized_model_name}")
        sanitized_model_name = sanitized_model_name[:15]  # Limit length

        timestamp = datetime.now().strftime("%m%d_%H%M")
        output_name = (
            f"events_{timestamp}_{sanitized_model_name}_{self.source_json_name}"
        )
        output_path = os.path.join(output_dir, output_name)

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)

        logger.info(
            f"Saved {len(result['events'])} events from model {model_name} to {output_path}"
        )


async def process_file(
    filename: str,
    reload: bool = False,
    use_working_file: bool = False,
) -> None:
    """Process a file by extracting content and events."""
    logger.info(f"Starting processing of file: {filename}")

    # Create working file
    data = create_working_file(filename, reload=reload)
    working_filename = f"{filename[:-5]}{WORKING_FILE_SUFFIX}.json"
    filepath = os.path.join(MESSAGES_DIR, working_filename)
    logger.info(f"Working with: {working_filename}")

    # Initialize processor
    processor = MessagesProcessor(filepath=filepath)

    # Process images and links only if not using existing working file
    if not use_working_file:
        # Process images
        await processor.process_images()

        # Process links
        await processor.process_links()
    else:
        logger.info("Using existing working file - skipping image and link processing")

    # Extract events (automatically uses multiple models if configured in .env)
    await processor.extract_events()

    logger.info(f"Successfully processed: {filename}")


async def main() -> None:
    """Main entry point for processing WhatsApp message files."""
    try:
        test_filename = "messages_20250630_1218.json"

        # Configuration flags
        reload_file = True
        use_working_file = not reload_file

        # Process file with task-based model selection
        # Models are automatically selected based on .env configuration
        await process_file(
            test_filename,
            reload=reload_file,
            use_working_file=use_working_file,
        )

    finally:
        # Ensure the httpx client is properly closed
        logger.info("Closing httpx client")
        await close_httpx_client()

        # Play a simple notification sound
        try:
            if platform.system() == "Windows":
                winsound.Beep(1000, 1000)
            logger.info("Completion sound played (if supported).")
        except Exception as sound_error:
            logger.warning(f"Could not play completion sound: {sound_error}")


if __name__ == "__main__":
    asyncio.run(main())
