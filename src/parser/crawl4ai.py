"""Crawl4AI integration module for URL content extraction and processing.

Provides web crawling capabilities with Cloudflare bypass support via Flaresolverr,
LLM-based content analysis, and structured event data extraction.
"""

import asyncio
import hashlib
import json
import os
import random
import string
from datetime import datetime
from typing import Any, Dict, List, Optional

import instructor
import litellm
from aiolimiter import AsyncLimiter
from config.config import CRAWL4AI_PROFILE_DIR, ACTIVATE_FLARESOLVERR, CRAWLED_EVENTS_DIR, FLARESOLVERR_CONFIG, FLARESOLVERR_DO_AUTH, FLARESOLVERR_USERNAME, FLARESOLVERR_PASSWORD
from src.parser.info.llm_prompts import EventDetail, EventDetailNoLinks
from src.parser.info.models import get_model_config, get_model_limiter
from config.config import LITELLM_API_KEY
from crawl4ai import *
from crawl4ai.async_dispatcher import SemaphoreDispatcher
from crawl4ai.content_scraping_strategy import LXMLWebScrapingStrategy
from litellm import acompletion
from pydantic import BaseModel, Field
from src.parser.api import instructor_chat_completion
from src.parser.flaresolverr import AsyncFlaresolverrClient
from src.parser.utils import is_blacklisted

# Setup logging using centralized config
from config.logs import get_logger
logger = get_logger(__name__)


async def process_markdown_with_llm(
    url: str,
    markdown_content: str,
    model_key: str,
    use_links_model: bool = True,
) -> dict:
    """Process markdown content with LLM to extract event details."""
    try:
        # Get model configuration and rate limiter
        model_config = get_model_config(model_key)
        model_limiter = get_model_limiter(model_key)
        
        async with model_limiter:
            process_response = {
                "llm_success": True,
                "llm_error": None,
                "llm_response": None,
            }

            system_prompt = (
                f"You are now an Event Information Extractor. Based on the above content from the URL, determine if it describes a public, attendable event."
                f"If it is an event, extract a comprehensive, verbose and extensive description of the main event including all details. Only extract information from the main, prominent event on the page ignoring minor mentions of other events."
            )

            if use_links_model:
                system_prompt += (
                    f"Based on the links in the page, add upto two additional links for further parsing that are likely to contain more information or registration about the main event. Do not add links that are not relevant to the main event."
                )

            response_model = EventDetail if use_links_model else EventDetailNoLinks

            event_extraction = await instructor_chat_completion(
                model=model_config["name"],
                response_model=response_model,
                system_prompt=system_prompt,
                content=f"URL: {url}\n\nContent:\n{markdown_content}\n\n",
                tool_mode=model_config.get("tool_mode", "json"),
                route=model_config["route"],
                reasoning=model_config.get("reasoning"),
                model_key=model_key,
            )

            process_response["llm_response"] = event_extraction.model_dump()
            return process_response

    except Exception as e:
        logger.error(f"LLM processing error for {url}: {str(e)}")
        return {
            "llm_success": False,
            "llm_error": str(e),
            "llm_response": None,
        }


def get_html_cloudflare_link_sync(client, url, use_cache: bool = True):
    """
    Synchronously process a single URL through Flaresolverr using robust session management with caching.

    Args:
        client: AsyncFlaresolverrClient instance
        url: Single URL to process
        use_cache: Whether to use cached results if available

    Returns:
        HTML content as string, or None if failed
    """
    logger.info(f"Processing URL: {url}")

    # Use the robust get_url_sync method which handles all session management internally
    html_content = client.get_url_sync(url, use_cache=use_cache)

    if html_content is not None:
        logger.info(f"Successfully processed URL: {url}")
        return html_content
    else:
        logger.error(f"Failed to process URL after all pathways: {url}")
        return None


async def crawl_and_process_url_many(
    urls: List[str],
    crawler,
    run_cfg: CrawlerRunConfig,
    flaresolverr_client: Optional[AsyncFlaresolverrClient],
    html_cfg: CrawlerRunConfig,
    dispatcher,
    model_key: str,
    use_links_model: bool = True,
    activate_flaresolverr: bool = True,
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
                "/cdn-cgi/styles/cf.errors.css",
            ]
        ):
            logger.warning(f"Cloudflare challenge detected for URL: {url}")
            cloudflare_urls.append(url)
            cloudflare_indices.append(i)

    # Handle Cloudflare challenges if any detected and Flaresolverr is activated
    if cloudflare_urls and activate_flaresolverr and flaresolverr_client:
        logger.info(
            f"Processing {len(cloudflare_urls)} URLs with Cloudflare challenges using Flaresolverr"
        )

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
    elif cloudflare_urls and not activate_flaresolverr:
        logger.info(
            f"Skipping {len(cloudflare_urls)} URLs with Cloudflare challenges (Flaresolverr disabled)"
        )
        html_results = {}
    elif cloudflare_urls and not flaresolverr_client:
        logger.warning(
            f"Skipping {len(cloudflare_urls)} URLs with Cloudflare challenges (no Flaresolverr client provided)"
        )
        html_results = {}
    else:
        html_results = {}

    # Process all Cloudflare HTML content in parallel using arun_many (only if we have results)
    if html_results:
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
                "/cdn-cgi/styles/cf.errors.css",
            ]
        ):
            if activate_flaresolverr:
                logger.error(
                    f"Cloudflare challenge still present after processing for URL: {url}"
                )
            else:
                logger.info(
                    f"Cloudflare challenge detected for URL: {url} (Flaresolverr disabled, skipping)"
                )
            continue

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
                model_key,
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


async def crawl_and_extract_event_details_from_urls(
    urls: List[str], model_key: str = None
) -> Dict[str, Any]:
    """
    Crawl and extract event details from a list of URLs.

    Args:
        urls: List of URLs to process
        model_key: Model key for HTML parsing task

    Returns:
        Dictionary mapping URLs to their processing results
    """
    if not urls:
        logger.warning("No URLs provided for crawling")
        return {}

    logger.info(f"Processing {len(urls)} URLs using Crawl4AI")

    # Ensure we have a chrome profile directory
    user_data_path = str(CRAWL4AI_PROFILE_DIR)

    if not os.path.exists(user_data_path):
        os.makedirs(user_data_path, exist_ok=True)
        logger.info(f"Created Crawl4AI profile directory: {user_data_path}")

    # Setup configurations
    browser_cfg = BrowserConfig(
        headless=False,
        browser_mode="builtin",
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        ),
        # use_persistent_context=True,
        user_data_dir=user_data_path,
        viewport={"width": 1920, "height": 1080},
        extra_args=[
            "--disable-blink-features=AutomationControlled",
            "--disable-infobars",
            "--start-maximized",
            "--disable-dev-shm-usage",
            "--disable-setuid-sandbox",
        ],
        ignore_https_errors=True,
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
        cache_mode=CacheMode.DISABLED,
        page_timeout=4 * 60 * 1000,
        scan_full_page=True,
        scroll_delay=1,
        delay_before_return_html=20,
        remove_overlay_elements=True,
        magic=True,
        process_iframes=True,
        simulate_user=True,
        override_navigator=True,
        scraping_strategy=LXMLWebScrapingStrategy(),
    )

    html_cfg = CrawlerRunConfig(
        scraping_strategy=LXMLWebScrapingStrategy(),
        verbose=False,
    )

    # Instantiate Flaresolverr client only if activated
    flaresolverr_client = None
    if ACTIVATE_FLARESOLVERR:
        flaresolverr_client = AsyncFlaresolverrClient(
            flaresolverr_url=FLARESOLVERR_CONFIG["url"],
            use_auth=FLARESOLVERR_DO_AUTH,
            username=FLARESOLVERR_USERNAME,
            password=FLARESOLVERR_PASSWORD
        )
        logger.info(f"Flaresolverr activated for Cloudflare bypass at {FLARESOLVERR_CONFIG['url']}")
        if FLARESOLVERR_DO_AUTH:
            logger.info("Flaresolverr using HTTP Basic Authentication")
    else:
        logger.info("Flaresolverr disabled - Cloudflare challenges will be skipped")

    # Use configured crawled events output directory
    outputs_dir = str(CRAWLED_EVENTS_DIR)

    # Get model configuration
    if not model_key:
        from src.parser.info.models import get_model_for_task
        model_key = get_model_for_task("html_parsing")

    model_config = get_model_config(model_key)
    model_name = model_config["name"]

    # Create output file with timestamp and model name for debugging
    model_for_filename = model_name.split("/")[-1].replace("-", "_").lower()
    output_file = os.path.join(
        outputs_dir,
        f"crawl4ai_events_{datetime.now().strftime('%Y-%m-%d_%H-%M')}_{model_for_filename}.json",
    )

    # Track URLs and results
    processed_urls = set()
    results = {}

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
                model_key,
                use_links_model=True,
                activate_flaresolverr=ACTIVATE_FLARESOLVERR,
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
                    model_key,
                    use_links_model=False,
                    activate_flaresolverr=ACTIVATE_FLARESOLVERR,
                )

                # Add results from additional links
                for result in additional_results:
                    url = result["url"]
                    results[url] = {k: v for k, v in result.items() if k != "url"}

    # Save results to a file for debugging
    try:
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        logger.info(f"Crawl4AI results saved to {os.path.abspath(output_file)}")
    except Exception as e:
        logger.error(f"Error writing crawl4ai results to file: {str(e)}")

    return results
