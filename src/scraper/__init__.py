"""WhatsApp Web scraper package.

Provides clean, modular components for WhatsApp Web automation including:
- Browser session management and authentication
- Message parsing and extraction
- Group navigation and scraping orchestration
"""

from .browser import BrowserManager
from .message_parser import MessageParser
from .whatsapp_scraper import WhatsAppScraper

__all__ = ["BrowserManager", "MessageParser", "WhatsAppScraper"]
