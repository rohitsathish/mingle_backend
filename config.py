# %%
import os
from typing import Dict
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

# Directory for message files
MESSAGES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "messages")

# Time deltas
NEW_FILE_THRESHOLD = timedelta(
    hours=12
)  # Create new file if last file is older than this
GROUP_SCRAPE_THRESHOLD = timedelta(
    hours=12
)  # Rescrape group if last scrape is older than this


# Number of days to look back for messages
DAYS_BACK_TO_PROCESS = 10

# Currently in main chat - Swapbook, the reading social, Under the lamp, Twotablesclub, Read a kitaab announcement group
# Yet to add board gaming groups

# Group configurations with chatter flag
GROUPS: Dict[str, Dict[str, bool]] = {
    "HUMAN LIBRARY BENGALURU": {"chatter": False},
    "Copper + Cloves Happenings": {"chatter": False},
    "the STUDIO by Copper + Cloves": {"chatter": False},
    "BCC Community": {"chatter": False},
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
    # Chatty groups
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

GROUP_CONTACT_DETAILS: Dict[str, Dict[str, str]] = {
    "BLR Events Hub": {
        "Instagram": "https://instagram.com/blreventshub/",
        "WhatsApp Group": "https://chat.whatsapp.com/DIlXUSSkjQ95uFiYrfZ03v",
    }
}

PRIVATE_GROUPS: Dict[str, Dict[str, bool]] = {
    "Poker club HSR": {"chatter": True},
    "FCB - Events": {"chatter": True},
    "TGIF Ultimate Pick Up": {"chatter": True},
    "Bengaluru Picklers": {"chatter": True},
    "Bengaluru Foodies Community": {"chatter": False},
}

# Output file path
MESSAGES_JSON_PATH = os.path.join(
    MESSAGES_DIR,
    f"messages_{datetime.now(ZoneInfo('Asia/Kolkata')).strftime('%Y%m%d_%H%M')}.json",
)

# Event-related patterns for filtering messages in verbose groups
EVENT_PATTERNS = [
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

# DOM Selectors for WhatsApp Web Elements
SELECTORS = {
    "MAIN_PAGE_HEADER": 'button[aria-label="Chats"]',
    "ARCHIVED_TEXT": 'div:text-is("Archived")',
    "ARCHIVED_HEADER": 'h1:has-text("Archived")',
    "GROUP_CONTAINER": 'div[role="group"]',
    "ARCHIVED_GROUPS": '//h1[text()="Archived"]/ancestor::header/following-sibling::div//div[@role="gridcell"]//span[@dir="auto"]',
    "CHAT_CONTAINER": "main",
    "SCROLL_CONTAINER": '//h1[text()="Archived"]/ancestor::header/following-sibling::div',
    "SYNC_ICON": 'div[data-icon*="sync"]:has(> div:contains("sync"))',
    "CHAT_SCROLL_BOTTOM_BUTTON": 'div[role="button"][aria-label="Scroll to bottom"]',
    "READ_MORE_BUTTON": 'div[class*="copyable-text"] > div > div[role="button"]:text-is("Read more")',
    "MESSAGE_DATE_DIVS": 'div[role="application"] > div[tabindex="-1"] > div > span[dir="auto"]',
    "OLDER_MESSAGES_BUTTON": ':text-matches("click here to get older messages", "i")',
    "USE_PHONE_MESSAGE": ':text-matches("Use WhatsApp on your phone to see older", "i")',
    "SYNC_PAUSED_MESSAGE": ':text-matches("Syncing paused. Open whatsapp", "i")',
    "SYNC_PROGRESS_MESSAGE": ':text-matches("Syncing older messages", "i")',
    "CHAT_SCROLL_CONTAINER": 'div[id="main"] > div > div[class*="copyable-area"] > div[tabindex="0"]',
    "MESSAGE_CONTAINER": 'div[role="application"] > div',
    "MESSAGE_TEXT": 'span[dir="ltr"]',
    "MESSAGE_EVENT": 'div[aria-label*="Event"]',
    "MESSAGE_DATE_HEADER": 'span[dir="auto"]',
}

CATEGORY_TAG_LIST = {
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
        "children’s workshop",
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

# %%

list(CATEGORY_TAG_LIST.keys())
