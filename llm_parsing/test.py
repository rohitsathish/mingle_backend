# %%
urls_to_scrape = [
    # "https://app.venn.buzz/social_experience/4581",
    # "https://bit.ly/4k9jNd6",
    # "https://www.scrapingcourse.com/antibot-challenge",
    "https://t.ly/xjiIU",
    "https://t.ly/hu3es",
    "https://t.ly/Fhn83",
]

# %%

import nest_asyncio
import asyncio
import os
from api import crawl_and_extract_event_details_from_urls


async def test():
    sum_ = 0
    for i in range(100):
        sum_ += i
    return sum_


async def main():
    resp = await crawl_and_extract_event_details_from_urls(urls_to_scrape)
    print(resp)


asyncio.run(main())

# %%

import requests
import json
from typing import Dict, Optional

from crawl4ai import LXMLWebScrapingStrategy


class FlaresolverrClient:
    """
    A Python client for interacting with a Flaresolverr instance.
    Manages session creation, requests, and destruction.
    """

    def __init__(self, flaresolverr_url: str = "http://localhost:8191/v1"):
        """
        Initializes the client.

        Args:
            flaresolverr_url: The base URL of the Flaresolverr API.
        """
        self.base_url = flaresolverr_url
        self.active_sessions: Dict[str, str] = {}  # To store session IDs

    def create_session(self, session_id: str) -> bool:
        """
        Creates a new browser session in Flaresolverr.

        Args:
            session_id: A unique name for the session (e.g., the website's domain).

        Returns:
            True if the session was created successfully, False otherwise.
        """
        print(f"Creating Flaresolverr session: {session_id}...")
        payload = {"cmd": "sessions.create", "session": session_id}
        try:
            response = requests.post(self.base_url, json=payload, timeout=30)
            response.raise_for_status()  # Raises HTTPError for bad responses (4xx or 5xx)
            data = response.json()
            if data.get("status") == "ok":
                self.active_sessions[session_id] = session_id
                print(f"Session '{session_id}' created successfully.")
                return True
            else:
                print(f"Error creating session: {data.get('message')}")
                return False
        except requests.exceptions.RequestException as e:
            print(f"Failed to connect to Flaresolverr: {e}")
            return False

    def get_url(
        self, url: str, session_id: Optional[str] = None, timeout_ms: int = 60000
    ) -> Optional[str]:
        """
        Fetches a URL, optionally using an existing session.

        Args:
            url: The URL to fetch.
            session_id: The session to use. If None, a session-less request is made.
            timeout_ms: Timeout for the request in milliseconds.

        Returns:
            The HTML content of the page as a string, or None if it failed.
        """
        print(
            f"Requesting URL: {url} {'with session ' + session_id if session_id else ''}"
        )
        payload = {"cmd": "request.get", "url": url, "maxTimeout": timeout_ms}
        if session_id and session_id in self.active_sessions:
            payload["session"] = session_id

        try:
            response = requests.post(
                self.base_url, json=payload, timeout=(timeout_ms / 1000) + 10
            )  # Python timeout in seconds
            response.raise_for_status()
            data = response.json()

            if data.get("status") == "ok":
                print("URL fetched successfully.")
                return data["solution"]["response"]  # This is the clean HTML
            else:
                print(
                    f"Flaresolverr returned an error for {url}: {data.get('message')}"
                )
                return None
        except requests.exceptions.RequestException as e:
            print(f"Failed to fetch {url} via Flaresolverr: {e}")
            return None

    def destroy_session(self, session_id: str) -> bool:
        """
        Destroys a browser session in Flaresolverr.

        Args:
            session_id: The name of the session to destroy.

        Returns:
            True if successful, False otherwise.
        """
        if session_id not in self.active_sessions:
            print(f"Session '{session_id}' not found.")
            return False

        print(f"Destroying Flaresolverr session: {session_id}...")
        payload = {"cmd": "sessions.destroy", "session": session_id}
        try:
            response = requests.post(self.base_url, json=payload, timeout=30)
            response.raise_for_status()
            data = response.json()
            if data.get("status") == "ok":
                del self.active_sessions[session_id]
                print(f"Session '{session_id}' destroyed successfully.")
                return True
            else:
                print(f"Error destroying session: {data.get('message')}")
                return False
        except requests.exceptions.RequestException as e:
            print(f"Failed to destroy session: {e}")
            return False


# client = FlaresolverrClient()

# client.create_session("example_session")

# markdown_converter = LXMLWebScrapingStrategy()

# from crawl4ai.async_configs import CrawlerRunConfig
# from crawl4ai import LXMLWebScrapingStrategy, AsyncWebCrawler, CacheMode
# import asyncio

# # for url in urls_to_scrape:
# #     html_content = client.get_url(url, session_id="example_session")
# #     if html_content:
# #         print(f"Fetched content from {url} successfully. \n Content Fetched: {html_content[:500]}...")  # Print first 100 characters
# #     else:
# #         print(f"Failed to fetch content from {url}.")

# for url in urls_to_scrape:
#     print(f"\n--- Processing URL: {url} ---")
#     html_content = client.get_url(url, session_id="example_session")

#     if html_content:
#         print(
#             "Successfully fetched HTML. Passing to crawl4ai for markdown conversion..."
#         )

#         raw_html = f"raw:{html_content}"
#         get_html_cfg = CrawlerRunConfig(
#             cache_mode=CacheMode.DISABLED,
#             scraping_strategy=LXMLWebScrapingStrategy(),
#         )

#         async def get_html_content(raw_html: str):
#             async with AsyncWebCrawler() as crawler:
#                 result = await crawler.arun(
#                     url=raw_html,
#                     config=get_html_cfg
#                 )
#                 if result.success:
#                     print("Markdown content: ", result.markdown, "...")
#                 else:
#                     print("Failed to fetch Markdown content.")

#         asyncio.run(get_html_content(raw_html))
#     else:
#         print(f"Failed to fetch HTML content from {url}.")

# %%

from api import AsyncFlaresolverrClient, HTTPX_CLIENT
import asyncio
from crawl4ai import *

# import nest_asyncio

# nest_asyncio.apply()  # Apply nest_asyncio to allow nested event loops

# client = AsyncFlaresolverrClient(
#     flaresolverr_url="http://localhost:8191/v1",
# )


async def main():
    client = AsyncFlaresolverrClient(
        flaresolverr_url="http://localhost:8191/v1",
    )
    await client.create_session("example_session")

    for url in urls_to_scrape:
        print(f"\n--- Processing URL: {url} ---")
        html_content = await client.get_url(url, session_id="example_session")

        if html_content:
            print(
                "Successfully fetched HTML. Passing to crawl4ai for markdown conversion..."
            )

            raw_html = f"raw:{html_content}"
            get_html_cfg = CrawlerRunConfig(
                cache_mode=CacheMode.DISABLED,
                scraping_strategy=LXMLWebScrapingStrategy(),
            )

            async def get_html_content(raw_html: str):
                async with AsyncWebCrawler() as crawler:
                    result = await crawler.arun(url=raw_html, config=get_html_cfg)
                    if result.success:
                        print("Markdown content: ", result.markdown, "...")
                    else:
                        print("Failed to fetch Markdown content.")

            await get_html_content(raw_html)
        else:
            print(f"Failed to fetch HTML content from {url}.")


# if __name__ == "__main__":
#     asyncio.run(main())
# asyncio.run(client.destroy_session("example_session"))
# print("Session destroyed.")
