"""Message processing module for extracting events from WhatsApp messages."""

import asyncio
import json
import logging
import os
import shutil
import sys
from typing import Any, Dict, List, Optional
import tiktoken
from urlextract import URLExtract

from config_llm import (
    MESSAGES_DIR,
    OPENROUTER_MODELS,
    SYSTEM_PROMPT,
    WORKING_FILE_SUFFIX,
    EventResponse,
    ImageDescription,
)
from llm_parsing.api_t import (
    close_httpx_client,
    get_link_markdown,
    instructor_chat_completion,
)

# Configure minimal logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# URL extractor instance
url_extractor = URLExtract()


def create_working_file(original_filename: str, reload: bool = False) -> Dict[str, Any]:
    """Creates or loads a working copy of a message JSON file."""
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
        chunk_stats.append(
            f"Chunk {i+1}: {len(chunk['whatsapp_groups'])} groups, ~{token_count} tokens"
        )

    logger.info(
        f"Created {len(chunks)} chunks from {len(data.get('whatsapp_groups', []))} groups"
    )
    for stat in chunk_stats:
        logger.info(stat)

    return chunks


async def process_with_progress(tasks, description="Processing"):
    """Process async tasks with progress tracking."""
    total = len(tasks)
    if not total:
        logger.info(f"No tasks to process for: {description}")
        return []

    logger.info(f"{description} ({total} items)...")
    completed = 0

    running_tasks = {
        asyncio.create_task(task, name=f"task_{i}"): i for i, task in enumerate(tasks)
    }
    results = [None] * total

    try:
        pending = set(running_tasks.keys())
        while pending:
            done, pending = await asyncio.wait(
                pending, return_when=asyncio.FIRST_COMPLETED
            )

            for task in done:
                index = running_tasks[task]
                try:
                    results[index] = task.result()
                    completed += 1

                    if completed % max(1, total // 10) == 0 or completed == total:
                        logger.info(
                            f"Progress: {completed}/{total} ({int(completed/total*100)}%)"
                        )

                except Exception as e:
                    for pending_task in pending:
                        pending_task.cancel()
                    logger.error(f"Task error at {index+1}/{total}: {str(e)}")
                    raise

    except Exception as e:
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        logger.error(f"Processing failed after completing {completed}/{total} tasks")
        raise

    logger.info(f"Completed: {completed}/{total} ({int(completed/total*100)}%)")
    return results


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
        model_name = OPENROUTER_MODELS["gemini-2.5-pro"]["name"]

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
                                model=model_name,
                                response_model=ImageDescription,
                                content="Is this image related to a potential event announcement or poster? If so, extract all relevant event details.",
                                image_urls=[base64_img],
                            )
                        )

        if not coroutines:
            logger.info("No images found to process")
            return

        # Process images with progress tracking
        results = await process_with_progress(coroutines, "Processing images")

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
        """Extract URLs, fetch content, and update messages."""
        logger.info("Processing URLs")

        # Extract and filter URLs
        url_locations = {}
        unique_urls = set()

        for group_index, group in enumerate(self.data.get("whatsapp_groups", [])):
            for msg_key, msg_list in group.get("messages", {}).items():
                for msg_part_index, msg_part in enumerate(msg_list):
                    if not isinstance(msg_part, dict) or "text" not in msg_part:
                        continue

                    text = msg_part.get("text", "")
                    if not text:
                        continue

                    found_urls = url_extractor.find_urls(text)
                    location = (group_index, msg_key, msg_part_index)

                    for url in found_urls:
                        url = url.rstrip("/")  # Normalize URL
                        unique_urls.add(url)

                        if url not in url_locations:
                            url_locations[url] = []
                        if location not in url_locations[url]:
                            url_locations[url].append(location)

        # Filter URLs to remove blacklisted ones
        filtered_urls = {url for url in unique_urls if not self._is_blacklisted(url)}
        logger.info(f"Found {len(filtered_urls)} URLs to process after filtering")

        if not filtered_urls:
            logger.info("No URLs to process")
            return

        # Fetch content for each URL
        markdown_tasks = [get_link_markdown(url) for url in filtered_urls]
        results = await process_with_progress(markdown_tasks, "Fetching URL content")

        # Map results to URLs
        url_markdown_map = {}
        error_count = 0

        for url, result in zip(filtered_urls, results):
            if isinstance(result, Exception):
                error_count += 1
                logger.error(f"Failed to get content for URL {url}: {str(result)}")
                continue
            if result is not None:
                url_markdown_map[url] = result

        # Critical error - if all URLs failed to process
        if error_count == len(filtered_urls) and len(filtered_urls) > 0:
            raise RuntimeError(
                f"Critical failure: All {error_count} URL requests failed"
            )

        logger.info(
            f"Successfully fetched content for {len(url_markdown_map)}/{len(filtered_urls)} URLs"
        )

        # Update data with markdown content
        appended = 0
        update_errors = 0

        for url, locations in url_locations.items():
            if url not in url_markdown_map or not url_markdown_map[url]:
                continue

            content = url_markdown_map[url]

            for group_index, msg_key, msg_part_index in locations:
                try:
                    msg_part = self.data["whatsapp_groups"][group_index]["messages"][
                        msg_key
                    ][msg_part_index]

                    # Initialize text field if missing
                    if "text" not in msg_part:
                        msg_part["text"] = ""

                    # Add markdown content
                    prefix = f"\n[Content from link {url}]: {content}\n"

                    # Avoid adding duplicate content
                    if prefix not in msg_part["text"]:
                        msg_part["text"] += prefix
                        appended += 1

                except (KeyError, IndexError, TypeError) as e:
                    update_errors += 1
                    logger.error(f"Error updating message with URL content: {str(e)}")

        logger.info(
            f"Added content for {len(url_markdown_map)} URLs across {appended} message locations"
        )

        # Save updated data if we have a filepath
        if self.filepath:
            with open(self.filepath, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2, ensure_ascii=False)

    async def extract_events(self, model_list: List[str]) -> Optional[Dict[str, Any]]:
        """Extract events from messages using specified models."""
        logger.info("Extracting events from messages")

        if not model_list:
            model_list = ["gemini-2.5-pro"]

        test_mode = len(model_list) > 1
        output_dir = os.path.dirname(self.filepath) if self.filepath else MESSAGES_DIR

        # Prepare model configurations
        model_configs = []
        for model_name in model_list:
            # Get model details from OPENROUTER_MODELS
            if model_name in OPENROUTER_MODELS:
                model_detail = OPENROUTER_MODELS[model_name]
                actual_model = model_detail["name"]
                token_limit = int(model_detail.get("input_tokens", 90000))
            else:
                # If model not found in config, use as-is with default token limit
                actual_model = model_name
                token_limit = 90000
                logger.warning(
                    f"Model {model_name} not found in OPENROUTER_MODELS, using default token limit"
                )

            model_configs.append((model_name, actual_model, token_limit))

        # Process each model - if multiple models, process them in parallel
        if test_mode:
            # Create coroutines for processing each model
            model_tasks = [
                self._process_model(model_name, actual_model, token_limit, output_dir)
                for model_name, actual_model, token_limit in model_configs
            ]

            # Execute all model processing tasks with progress tracking
            logger.info(f"Processing {len(model_tasks)} models in parallel")
            results = await process_with_progress(model_tasks, "Processing models")

            # Filter out None results
            all_results = [result for result in results if result is not None]
            logger.info(
                f"Successfully processed {len(all_results)}/{len(model_list)} models"
            )

            return None  # In test mode, results are saved to files
        else:
            # Single model - process directly
            model_name, actual_model, token_limit = model_configs[0]
            logger.info(f"Processing with model: {model_name}")

            return await self._process_model(
                model_name, actual_model, token_limit, output_dir
            )

    async def _process_model(
        self, model_name: str, actual_model: str, token_limit: int, output_dir: str
    ) -> Optional[Dict[str, Any]]:
        """Process messages with a specific model."""
        try:
            # Create chunks based on token limit
            chunks = create_message_chunks(
                self.data, SYSTEM_PROMPT, token_limit=token_limit
            )

            # Process all chunks for this model in parallel
            chunk_tasks = [
                self._process_chunk(chunk, actual_model, i, len(chunks))
                for i, chunk in enumerate(chunks)
            ]

            # Execute all chunk processing tasks with progress tracking
            logger.info(f"Processing {len(chunk_tasks)} chunks with model {model_name}")
            chunk_results = await process_with_progress(
                chunk_tasks, f"Processing chunks with {model_name}"
            )

            # Filter out None results
            chunk_results = [result for result in chunk_results if result is not None]

            # Combine results from all chunks
            combined_result = self._combine_responses(chunk_results)

            # Save results if we have multiple models
            if len(OPENROUTER_MODELS) > 1:
                self._save_results(combined_result, model_name, output_dir)

            return combined_result

        except Exception as e:
            logger.error(f"Error processing model {model_name}: {e}")
            return None

    async def _process_chunk(
        self, chunk: Dict[str, Any], model: str, chunk_index: int, total_chunks: int
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
            # Process this chunk with LLM
            response = await instructor_chat_completion(
                model=model,
                response_model=EventResponse,
                content=content,
                system_prompt=SYSTEM_PROMPT,
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

            # Add all new categories - structure has changed from category_updates.new_categories to just new_categories
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
        sanitized_model_name = sanitized_model_name[:10]  # Limit length
        if model_name == "gemini-2.5-pro":
            output_name = f"{self.source_json_name.replace('messages', 'events')}"
        else:
            output_name = f"events_{sanitized_model_name}_{self.source_json_name}"
        output_path = os.path.join(output_dir, output_name)

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)

        logger.info(
            f"Saved {len(result['events'])} events from model {model_name} to {output_path}"
        )

    @staticmethod
    def _is_blacklisted(url: str) -> bool:
        """Check if a URL should be blacklisted."""
        url_lower = url.lower()
        bad_links = [
            "maps.app.goo.gl",
            "maps.google",
            "chat.whatsapp.com",
            "linktr.ee",
        ]

        if any(domain in url_lower for domain in bad_links):
            return True

        # Special handling for Instagram: only allow post links (/p/)
        if "instagram.com" in url_lower and "/p/" not in url_lower:
            return True

        return False


async def process_file(
    filename: str,
    reload: bool = False,
    chunk_num: Optional[int] = None,
    model_list: Optional[List[str]] = None,
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

    # Process images
    await processor.process_images()

    # Process links
    await processor.process_links()

    # Set default model if not provided
    if not model_list:
        model_list = ["gemini-2.5-pro"]

    # Extract events
    await processor.extract_events(model_list)

    logger.info(f"Successfully processed: {filename}")


async def main() -> None:
    """Main entry point for processing WhatsApp message files."""
    try:
        test_filename = "messages_20250326_1425.json"

        # Define models to test - just list the model keys
        model_list = [
            "gemini-2.5-pro",
            # "gemini-2-flashthinking",
            # "qwen-32b",
            # "deepseek-r1",
        ]

        # Process file with multiple models
        await process_file(test_filename, reload=True, model_list=model_list)

    finally:
        # Ensure the httpx client is properly closed
        logger.info("Closing httpx client")
        await close_httpx_client()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Process interrupted by user")
    except Exception as e:
        logger.critical(f"Unhandled exception: {str(e)}")
        sys.exit(1)
