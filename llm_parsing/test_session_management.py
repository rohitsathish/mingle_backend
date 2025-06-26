#!/usr/bin/env python3
"""
Test script for the enhanced AsyncFlaresolverrClient session management.
"""

import os
import sys
import asyncio
import logging

# Add parent directory to path to import api
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from llm_parsing.api import AsyncFlaresolverrClient

# Setup logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


async def test_session_management():
    """Test the enhanced session management system."""

    # Initialize client
    client = AsyncFlaresolverrClient()

    # Test URLs (mix of easy and potentially problematic ones)
    test_urls = [
        "https://httpbin.org/html",  # Simple test
        "https://httpbin.org/delay/2",  # Slow response
        "https://example.com",  # Simple site
    ]

    logger.info("Testing enhanced AsyncFlaresolverrClient session management")
    logger.info(f"Session failure file: {client.session_failure_file}")

    # Show initial session state
    logger.info(f"Initial session failures: {client.session_failures}")
    active_sessions = client.get_active_session_ids()
    logger.info(f"Active sessions: {active_sessions}")

    # Test pathways for first URL
    pathways = client.get_url_pathways(test_urls[0])
    logger.info(f"URL pathways for {test_urls[0]}: {pathways}")

    # Test actual URL fetching
    for i, url in enumerate(test_urls):
        logger.info(f"\n--- Testing URL {i+1}/{len(test_urls)}: {url} ---")

        try:
            html_content = client.get_url_sync(url)
            if html_content:
                logger.info(
                    f"✓ Successfully fetched {url} ({len(html_content)} characters)"
                )
            else:
                logger.warning(f"✗ Failed to fetch {url}")
        except Exception as e:
            logger.error(f"✗ Exception fetching {url}: {e}")

    # Show final session state
    logger.info(f"\nFinal session failures: {client.session_failures}")

    # Test session retirement detection
    logger.info("\n--- Testing session retirement logic ---")

    # Simulate failures for a test session
    test_session = "test_session_failure"
    for i in range(6):  # 6 failures to test retirement
        client.record_session_result(test_session, False)
        is_retired = client.is_session_retired(test_session)
        logger.info(
            f"After {i+1} failures, session {test_session} retired: {is_retired}"
        )

    # Test recovery after success
    client.record_session_result(test_session, True)
    is_retired = client.is_session_retired(test_session)
    logger.info(f"After 1 success, session {test_session} retired: {is_retired}")

    logger.info("\nTest completed successfully!")


if __name__ == "__main__":
    # Run the test
    try:
        asyncio.run(test_session_management())
    except KeyboardInterrupt:
        logger.info("Test interrupted by user")
    except Exception as e:
        logger.error(f"Test failed with exception: {e}", exc_info=True)
