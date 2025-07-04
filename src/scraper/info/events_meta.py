"""
Event patterns and categories for Mingle Backend.

Defines patterns for detecting events in messages and categorizing them.
"""

from typing import Dict, List

# ============================================================================
# Event Detection Patterns
# ============================================================================

# Event-related patterns for filtering messages in verbose groups
EVENT_PATTERNS: List[str] = [
    # Core event indicators
    r"event",  # Generic event mention
    r"invite",
    r"meet-?up",  # Catches both meetup and meet-up
    r"last\s+chance",
    r"join\s+us",
    r"hosting",
    r"happening",
    r"save\s+the\s+date",
    r"mark\s+your\s+calendar",
    r"club",
    r"(?:this|next|coming)\s+weekend",
    # Time patterns (more specific)
    r"\d{1,2}(?::\d{2})?\s*(?:am|pm)",  # Matches time formats like "7pm", "7:30pm"
    r"this\s+(?:sat|sun|mon|tue|wed|thu|fri)(?:urday|day)?",  # Day mentions
    r"next\s+(?:sat|sun|mon|tue|wed|thu|fri)(?:urday|day)?",
    r"tomorrow\s+(?:evening|morning|afternoon)",
    # Registration/RSVP
    r"register\s+(?:here|now|at|via)",
    r"registration\s+(?:open|closes?|link)",
    r"rsvp",
    r"limited\s+(?:seats|spots)",
    # Event types (expanded)
    r"workshop",
    r"meetup",
    r"session",
    r"screening",
    r"performance\s+(?:by|of|at)",
    r"concert",
    r"exhibition",
    r"talk\s+(?:by|on|about)",
    r"seminar",
    r"discussion",
    r"panel\s+(?:on|about)",
    r"showcase\s+(?:of|by)",
    r"open\s+mic",
    r"jam\s+session",
    r"book\s+reading",
    r"art\s+(?:show|exhibition)",
    r"dance\s+(?:class|workshop|performance)",
    r"music\s+(?:show|night|performance)",
    r"poetry\s+(?:reading|session)",
    r"film\s+(?:screening|showing)",
    r"game\s+(?:night|session)",
    r"comedy\s+(?:show|night)",
    r"quiz\s+(?:night|competition)",
    r"food\s+(?:tasting|workshop)",
    r"networking\s+(?:event|session)",
    r"masterclass\s+(?:on|about|with)",
    r"live\s+(?:music|performance|show)",
    r"improv\s+(?:show|night|session)",
    # Entry/Tickets
    r"entry\s+(?:fee|is|:)",
    r"tickets?\s+(?:at|available|:)",
]

# ============================================================================
# Event Categories and Tags
# ============================================================================

CATEGORY_TAG_LIST: Dict[str, List[str]] = {
    "Reading & Literature": [
        "reading",
        "books",
    ],
    "Speaking & Discussion": ["debate", "storytelling", "discussion"],
    "Movies & Screenings": ["movie night", "screening", "short films"],
    "Performing Arts": [
        "theatre",
        "drama",
        "dance",
    ],
    "Music & Concerts": [
        "live music",
        "music festival",
    ],
    "Socializing & Meetups": [
        "social mixer",
        "networking event",
        "singles mixer",
        "meet & greet",
    ],
    "Food & Beverage": [
        "dining",
        "brunch",
        "lunch",
        "dinner",
    ],
    "Board Games & Tabletop": [
        "board games",
        "d&d",
        "dungeons & dragons",
        "chess meetup",
    ],
    "Open Mic & Poetry": ["poetry jam", "open mic night"],
    "Learning & Education": [
        "workshop",
        "class",
        "course",
        "training",
    ],
    "Sustainability & Environment": [
        "sustainability",
        "climate",
    ],
    "Community Service & Volunteering": [
        "volunteering",
        "charity",
        "fundraiser",
        "ngo event",
        "awareness drive",
    ],
    "Sports & Fitness": [
        "sports",
        "running",
        "cycling",
        "fitness",
        "workout",
        "yoga",
        "zumba",
        "marathon",
        "climbing",
        "martial arts",
    ],
    "Culture & Heritage": [
        "cultural event",
        "heritage walk",
    ],
    "Business & Entrepreunership": [
        "networking",
        "business meetup",
        "startup event",
        "conference",
        "hackathon",
    ],
    "Kids & Family": [
        "kids event",
        "children's workshop",
        "family event",
        "family-friendly",
        "kids activity",
        "parenting workshop",
    ],
    "Art & Craft": [
        "art fair",
        "craft fair",
        "exhibition",
        "art show",
        "handicrafts",
        "artisan market",
        "art gallery",
    ],
    "Health & Wellness": ["mental health", "yoga", "meditation"],
    "Travel & Adventure": [
        "hike",
        "trip",
    ],
    "Science & Tech": ["science lecture", "science gallery"],
    "Religion & Spirituality": ["astrology", "tarot reading", "bhajan"],
    "Pets & Animals": ["pet adoption", "wildlife retreat"],
}

# ============================================================================
# Utility Functions
# ============================================================================


def get_all_categories() -> List[str]:
    """Get list of all category names."""
    return list(CATEGORY_TAG_LIST.keys())


def get_tags_for_category(category: str) -> List[str]:
    """Get tags for a specific category."""
    return CATEGORY_TAG_LIST.get(category, [])


def find_categories_by_tag(tag: str) -> List[str]:
    """Find categories that contain a specific tag."""
    matching_categories = []
    tag_lower = tag.lower()

    for category, tags in CATEGORY_TAG_LIST.items():
        if any(tag_lower in t.lower() for t in tags):
            matching_categories.append(category)

    return matching_categories


def get_all_tags() -> List[str]:
    """Get all tags from all categories."""
    all_tags = []
    for tags in CATEGORY_TAG_LIST.values():
        all_tags.extend(tags)
    return list(set(all_tags))  # Remove duplicates


def compile_event_patterns() -> str:
    """Compile all event patterns into a single regex string."""
    return "|".join(f"({pattern})" for pattern in EVENT_PATTERNS)
