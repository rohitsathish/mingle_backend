"""LLM processing package for Mingle Backend.

This package provides structured LLM processing capabilities including:
- Flaresolverr client for Cloudflare bypass
- Unified instructor chat completion API
- Message processing and event extraction
- Crawl4AI integration for URL processing

Models and configurations are imported from config/ package.
"""

from .flaresolverr import AsyncFlaresolverrClient
from .api import instructor_chat_completion
from .crawl4ai import crawl_and_extract_event_details_from_urls

# Import MessagesProcessor only when accessed to avoid sys.modules conflicts
def __getattr__(name):
    if name == "MessagesProcessor":
        from .processor import MessagesProcessor
        return MessagesProcessor
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")

__all__ = [
    "AsyncFlaresolverrClient",
    "instructor_chat_completion",
    "crawl_and_extract_event_details_from_urls",
    "MessagesProcessor",
]
