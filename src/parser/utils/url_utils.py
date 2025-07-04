"""URL processing utilities for parser module."""


def is_blacklisted(url: str) -> bool:
    """Check if a URL should be blacklisted from processing.
    
    Combines URL filtering logic from both api.py and crawl4ai.py implementations.
    
    Args:
        url: The URL to check
        
    Returns:
        True if the URL should be blacklisted, False otherwise
    """
    if not isinstance(url, str):
        return True

    url_lower = url.lower()
    
    # Combined blacklist from both implementations
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