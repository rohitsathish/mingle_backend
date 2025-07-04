"""
DOM selectors for WhatsApp Web automation.

Contains all CSS selectors and XPath expressions used for scraping WhatsApp Web.
"""

from typing import Dict

# ============================================================================
# WhatsApp Web DOM Selectors
# ============================================================================

SELECTORS: Dict[str, str] = {
    # Main page navigation
    "MAIN_PAGE_HEADER": 'button[aria-label="Chats"]',
    "ARCHIVED_TEXT": 'div:text-is("Archived")',
    "ARCHIVED_HEADER": 'h1:has-text("Archived")',
    # Group containers and lists
    "GROUP_CONTAINER": 'div[role="group"]',
    "ARCHIVED_GROUPS": '//h1[text()="Archived"]/ancestor::header/following-sibling::div//div[@role="gridcell"]//span[@dir="auto"]',
    # Chat interface
    "CHAT_CONTAINER": "main",
    "SCROLL_CONTAINER": '//h1[text()="Archived"]/ancestor::header/following-sibling::div',
    "CHAT_SCROLL_CONTAINER": 'div[id="main"] > div > div[class*="copyable-area"] > div[tabindex="0"]',
    # UI controls
    "SYNC_ICON": 'div[data-icon*="sync"]:has(> div:contains("sync"))',
    "CHAT_SCROLL_BOTTOM_BUTTON": 'div[role="button"][aria-label="Scroll to bottom"]',
    "READ_MORE_BUTTON": 'div[class*="copyable-text"] > div > div[role="button"]:text-is("Read more")',
    "OLDER_MESSAGES_BUTTON": ':text-matches("click here to get older messages", "i")',
    # Message elements
    "MESSAGE_CONTAINER": 'div[role="application"] > div',
    "MESSAGE_TEXT": 'span[dir="ltr"]',
    "MESSAGE_EVENT": 'div[aria-label*="Event"]',
    "MESSAGE_DATE_HEADER": 'span[dir="auto"]',
    "MESSAGE_DATE_DIVS": 'div[role="application"] > div[tabindex="-1"] > div > span[dir="auto"]',
    # Status messages
    "USE_PHONE_MESSAGE": ':text-matches("Use WhatsApp on your phone to see older", "i")',
    "SYNC_PAUSED_MESSAGE": ':text-matches("Syncing paused. Open whatsapp", "i")',
    "SYNC_PROGRESS_MESSAGE": ':text-matches("Syncing older messages", "i")',
}

# ============================================================================
# Selector Categories for Organization
# ============================================================================

NAVIGATION_SELECTORS = {
    "MAIN_PAGE_HEADER": SELECTORS["MAIN_PAGE_HEADER"],
    "ARCHIVED_TEXT": SELECTORS["ARCHIVED_TEXT"],
    "ARCHIVED_HEADER": SELECTORS["ARCHIVED_HEADER"],
}

GROUP_SELECTORS = {
    "GROUP_CONTAINER": SELECTORS["GROUP_CONTAINER"],
    "ARCHIVED_GROUPS": SELECTORS["ARCHIVED_GROUPS"],
}

CHAT_SELECTORS = {
    "CHAT_CONTAINER": SELECTORS["CHAT_CONTAINER"],
    "SCROLL_CONTAINER": SELECTORS["SCROLL_CONTAINER"],
    "CHAT_SCROLL_CONTAINER": SELECTORS["CHAT_SCROLL_CONTAINER"],
}

MESSAGE_SELECTORS = {
    "MESSAGE_CONTAINER": SELECTORS["MESSAGE_CONTAINER"],
    "MESSAGE_TEXT": SELECTORS["MESSAGE_TEXT"],
    "MESSAGE_EVENT": SELECTORS["MESSAGE_EVENT"],
    "MESSAGE_DATE_HEADER": SELECTORS["MESSAGE_DATE_HEADER"],
    "MESSAGE_DATE_DIVS": SELECTORS["MESSAGE_DATE_DIVS"],
}

CONTROL_SELECTORS = {
    "SYNC_ICON": SELECTORS["SYNC_ICON"],
    "CHAT_SCROLL_BOTTOM_BUTTON": SELECTORS["CHAT_SCROLL_BOTTOM_BUTTON"],
    "READ_MORE_BUTTON": SELECTORS["READ_MORE_BUTTON"],
    "OLDER_MESSAGES_BUTTON": SELECTORS["OLDER_MESSAGES_BUTTON"],
}

STATUS_SELECTORS = {
    "USE_PHONE_MESSAGE": SELECTORS["USE_PHONE_MESSAGE"],
    "SYNC_PAUSED_MESSAGE": SELECTORS["SYNC_PAUSED_MESSAGE"],
    "SYNC_PROGRESS_MESSAGE": SELECTORS["SYNC_PROGRESS_MESSAGE"],
}

# ============================================================================
# Utility Functions
# ============================================================================


def get_selector(key: str) -> str:
    """Get a selector by key with validation."""
    if key not in SELECTORS:
        raise KeyError(
            f"Selector '{key}' not found. Available selectors: {list(SELECTORS.keys())}"
        )
    return SELECTORS[key]


def get_selectors_by_category(category: str) -> Dict[str, str]:
    """Get selectors by category."""
    categories = {
        "navigation": NAVIGATION_SELECTORS,
        "group": GROUP_SELECTORS,
        "chat": CHAT_SELECTORS,
        "message": MESSAGE_SELECTORS,
        "control": CONTROL_SELECTORS,
        "status": STATUS_SELECTORS,
    }

    if category not in categories:
        raise KeyError(
            f"Category '{category}' not found. Available categories: {list(categories.keys())}"
        )

    return categories[category]
