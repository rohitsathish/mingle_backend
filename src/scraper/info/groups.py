"""
WhatsApp group configuration for Mingle Backend.

Defines which groups to scrape and their characteristics.
"""

from typing import Dict

# ============================================================================
# WhatsApp Group Configurations
# ============================================================================

# Group configurations with chatter flag
# chatter=False: Announcement-only groups (cleaner data)
# chatter=True: Discussion groups (requires filtering)
GROUPS: Dict[str, Dict[str, bool]] = {
    "HUMAN LIBRARY BENGALURU": {"chatter": False},  # moved
    "Copper + Cloves Happenings": {"chatter": False},  # moved
    "the STUDIO by Copper + Cloves": {"chatter": False},  # moved
    "BCC Community": {
        "chatter": False
    },  # Its a bit confusing as there are two groups I guess. The ones available have been joined (2 communities and 1 group)
    "HSR Meetups Official": {"chatter": False},
    "BLR Events Hub": {"chatter": False},
    "No Pressure Improv!": {"chatter": False},
    "Courtyard Community": {"chatter": False},
    "New Acropolis Community": {"chatter": False},
    "The Parallel Cinema Club": {"chatter": False},
    "Science Gallery Bengaluru": {"chatter": False},
    "Sakura Screenings": {"chatter": False},
    "BangaloreDrumsCollective": {"chatter": False},
    "Atta Galatta - Events": {"chatter": False},
    "Improv Lore Community": {"chatter": False},
    "Underline Center": {"chatter": False},
    "The Mango Tree": {"chatter": False},
    "The UnListed Club": {"chatter": False},
    "Bangalore IRLs": {"chatter": False},
    "Bengaluru Social": {"chatter": False},
    "MAP Youth Collective": {"chatter": False},
    "Dialogues Friends": {"chatter": False},
    # "Putting Scene - 15": {"chatter": False},
    "Ekta's Gatherings": {"chatter": False},
    "BlrGrooveCo": {"chatter": False},
    # Chatty groups (require filtering)
    "BYOB-Bangalore": {"chatter": True},
    # "The Reading Social": {"chatter": True},
    # "Read A Kitaab: Bangalore": {"chatter": True},
    "Events BLR-BYOB": {"chatter": True},
    "Fit Club Bengaluru": {"chatter": True},
    "Sustainability101": {"chatter": True},
    "Terra.do Bangalore": {"chatter": True},
    "Bookmarks Lahe Lahe": {"chatter": True},
    "MOSAMBI: Bengaluru": {"chatter": True},
    "BSS monthly event updates": {"chatter": True},
    # Announcement Group Verification
    "Sanimawaale": {"chatter": True, "announce_gp": True},
}

# Private groups (separate from main scraping)
PRIVATE_GROUPS: Dict[str, Dict[str, bool]] = {
    "Poker club HSR": {"chatter": True},
    "FCB - Events": {"chatter": True},
    "TGIF Ultimate Pick Up": {"chatter": True},
    "Bengaluru Picklers": {"chatter": True},
    "Bengaluru Foodies Community": {"chatter": False},
}

# Group contact details (for reference)
GROUP_CONTACT_DETAILS: Dict[str, Dict[str, str]] = {
    "BLR Events Hub": {
        "Instagram": "https://instagram.com/blreventshub/",
        "WhatsApp Group": "https://chat.whatsapp.com/DIlXUSSkjQ95uFiYrfZ03v",
    }
}

# ============================================================================
# Utility Functions
# ============================================================================


def get_all_groups() -> Dict[str, Dict[str, bool]]:
    """Get all groups (both public and private)."""
    return {**GROUPS, **PRIVATE_GROUPS}


def get_announcement_groups() -> Dict[str, Dict[str, bool]]:
    """Get only announcement groups (chatter=False)."""
    return {
        name: config
        for name, config in GROUPS.items()
        if not config.get("chatter", False)
    }


def get_discussion_groups() -> Dict[str, Dict[str, bool]]:
    """Get only discussion groups (chatter=True)."""
    return {
        name: config for name, config in GROUPS.items() if config.get("chatter", False)
    }


def is_announcement_group(group_name: str) -> bool:
    """Check if a group is announcement-only."""
    return not GROUPS.get(group_name, {}).get("chatter", False)
