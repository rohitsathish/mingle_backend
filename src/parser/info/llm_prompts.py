"""
LLM prompt and data models for Mingle Backend.

Contains the system prompt and Pydantic models for event extraction.
"""

from datetime import datetime
from typing import Dict, List, Optional
from pydantic import BaseModel, Field
from src.scraper.info.events_meta import CATEGORY_TAG_LIST

# ============================================================================
# LLM System Prompt
# ============================================================================

SYSTEM_PROMPT = f"""You are an expert Event Information Extractor and Formatter AI. Your primary task is to meticulously analyze WhatsApp messages (with appended information) to identify and extract details about public events taking place in Bangalore and organize these into a structured output. You must be exhaustive in your search, ensuring no events are missed, and precise in your data formatting.

Core Tasks:

Event Identification:
1. Analyze if the message (text, image descriptions and url markdowns) contain information about a public event in Bangalore.
2. Disregard events occurring outside Bangalore. You may include online/virtual events.
3. Exclude events that appear to be private based on the message's tone, structure, and intended audience (e.g., casual language not directed to the public).
4. Focus on messages that indicate explicit event announcements, planning, discussions, registration/RSVP requests, venue updates, or follow-up details.
5. Consider the message date and content to infer event details. Be intelligent and use the message datetime, message and context of the messages, and use it to ignore past events.
6. 3 types of links can be isolated - info_link, reg_link and gmaps_link. Ensure that the same link is not placed in multiple fields.
7. Ensure that the same event is not duplicated by intelligently parsing the event details. However, if there are multiple instances/timings/occurrences of the same event at different times/places, create separate event entries for each (max. 3 instances of an event).

Important Considerations:
1. Accuracy and Completeness: Your output MUST be accurate and complete. Double-check the source data to ensure no events or details are missed.
2. Structured Output: The output MUST be strictly compatible with the provided output format. Ensure proper formatting, data types, and field names.
3. Thoroughness and Ambiguity: Be exhaustive in your search. Include the event as long as you can obtain the time, date and venue details (venue is not required for online/virtual events). If these are present and some other information is missing, include the event.

Allowed Categories:
{", ".join(CATEGORY_TAG_LIST.keys())}

Category Update Instructions:
- You may update the category list only if an event doesn't fit in any existing category
- Record any additions in the category_updates.new_categories array
- If no updates are needed, return an empty array for new_categories

Important: Today's date is {datetime.now().date()}. Use it to filter events that have already occurred.
"""

# ============================================================================
# Pydantic Data Models
# ============================================================================


class ImageDescription(BaseModel):
    """Pydantic model for extracting event information from images."""

    is_event_related: bool = Field(
        ...,
        description="True if the image contains information potentially related to an event (e.g., poster, announcement), False otherwise.",
    )
    event_description: str = Field(
        ...,
        description="Verbose description of any event-related information found in the image. Include details like event name, date, time, location, contact info, etc. If not event-related, return blank",
    )


class MultiImageDescription(BaseModel):
    """Pydantic model for extracting event information from multiple images."""

    images: List[ImageDescription] = Field(
        default_factory=list,
        description="List of image descriptions. Each entry should contain information about a single image in the order they were provided.",
    )


class Event(BaseModel):
    """Pydantic model for an event extracted from messages."""

    short_name: str = Field(
        ...,
        description="Shortened simple event name of length near but not exceeding 30 characters. Create a descriptive name but it need not be unique, so don't include the place or time details. Don't be vague, users should be able to understand what the event is about at a glance.",
    )
    name: str = Field(
        ...,
        description="The name of the event. Create a descriptive name if the name of the event is not directly provided. Don't include the place and time details.",
    )
    event_type: str = Field(
        ...,
        description="The type of event. Choose from the following options: 'online', 'IRL', 'hybrid'. Default to 'IRL' if unsure.",
    )
    categories: List[str] = Field(
        default_factory=list,
        description="A list of relevant categories that exactly match options from the allowed categories. You may add new categories ONLY if an event doesn't fit well into existing ones.",
    )
    tags: List[str] = Field(
        default_factory=list,
        description="An array of tags for the event. Create an extensive and long list of relevant tags (max 20) suited to keyword search. Tailor it to match potential, common keywords that a user might search for which this event would be a match. ",
    )
    summary: str = Field(
        ...,
        description="An informational and descriptive summary of the event. Don't include the place and time details.",
    )
    notes_to_admin: Optional[str] = Field(
        None,
        description="Use this to send any relevant information for developers (e.g., ambiguities, uncertainties). Only to be used when a critical alert, error or other info needs to be seen by a developer or admin.",
    )
    cost: Optional[float] = Field(
        None,
        description="The cost of the event in Indian Rupees. Use 0 for free events. If unsure from the context about whether its free or if there is a cost, set to null.",
    )
    source_whatsapp_group: Optional[str] = Field(
        None,
        description="The exact name of the WhatsApp group where the event was found.",
    )
    organizer: Optional[str] = Field(
        None,
        description="The name of the event organizer. May be a person, organization or group. In most cases, the the whatsapp group name provided is the organizer, in other cases its not. If unable to make a high probability guess, set to null. Don't include venue name here",
    )
    venue_name: Optional[str] = Field(
        None,
        description="The name of the venue where the event is taking place. If unable to make a high probability guess or online event, set to null.",
    )
    venue_address_llm: Optional[str] = Field(
        None,
        description="The venue address. Extract and format the address information provided, or generate the address if you know the venue. Generate an output that Google Places API can use to correctly identify the venue. If its unlikely that Google Places API will get the place correctly, is an online event, or you do not know the address, set to null.",
    )
    area: Optional[str] = Field(
        None,
        description="The area of the event in Bangalore. If the address or location details are not provided, you may, if reasonably confident, add this using your knowledge of Bangalore.",
    )
    post_datetime: Optional[str] = Field(
        None,
        description="The date and time when the event details were posted. Use the format: 'YYYY-MM-DDTHH:MM+05:30'.",
    )
    start_date: str = Field(
        ...,
        description="The date when the event is starting. If only date is given, put it here. Use the format: 'YYYY-MM-DD'.",
    )
    start_time: str = Field(
        ...,
        description="The time when the event is starting. Use the format: 'HH:MM+05:30'.",
    )
    end_date: Optional[str] = Field(
        None,
        description="The date when the event ends. Use the format: 'YYYY-MM-DD'. Set to start_date if you're reasonably confident its a one-day event (most are).",
    )
    end_time: Optional[str] = Field(
        None,
        description="The time when the event ends. Use the format: 'HH:MM+05:30'. Null if info is unavailable.",
    )
    is_update: bool = Field(
        False,
        description="Set to true if you suspect the event details are an update to a previous post for the same event; otherwise, false.",
    )
    is_cancelled: bool = Field(
        False,
        description="Set to true if the message indicates that a previous event is canceled; otherwise, false.",
    )
    info_link: Optional[str] = Field(
        None,
        description="Informational link about the event or organizer. Can be any link generally associated with the event. Set to null if not found.",
    )
    reg_link: Optional[str] = Field(
        None,
        description="Registration or payment link. A link that users may use to register for the event. Set to null if not found.",
    )
    gmaps_link: Optional[str] = Field(
        None,
        description="Google Maps link for the event location. Set to null if not found.",
    )


class EventResponse(BaseModel):
    """Complete response from event extraction process."""

    events: List[Event] = Field(
        default_factory=list, description="List of events extracted from the messages."
    )
    new_categories: List[str] = Field(
        default_factory=list,
        description="List of new categories suggested to be added to the existing category list. You may add new categories ONLY if an event didn't fit well into existing ones.",
    )


# ============================================================================
# URL Processing Models (for crawl4ai)
# ============================================================================

class EventDetail(BaseModel):
    """Event details model for crawl4ai URL processing with additional links."""
    
    is_event: bool = Field(
        description="Whether the content is related to a public, attendable event. If False, leave the rest of the fields empty."
    )
    is_expired: bool = Field(
        default=False,
        description="Whether the event content appears to be expired, outdated, or from a past date. Set to True if the page shows content that is clearly from the past or indicates the event has already occurred."
    )
    description: str = Field(
        description="Extensive, comprehensive information about the main event including (if details are available) the event date, time (in IST), location, cost and any other relevant information.",
        default="",
    )
    additional_links: List[str] = Field(
        default_factory=list,
        description="List of highly relevant links that are indicated to provide additional information about the specific event. These can include registration links, payment links or links with additional information. Do not include general links, calendar links or links that are not directly related to the event. Restrict the number of links to 2 or fewer. Leave empty if no such links are found.",
    )


class EventDetailNoLinks(BaseModel):
    """Event details model for crawl4ai URL processing without additional links."""
    
    is_event: bool = Field(
        description="Whether the content is related to a public, attendable event. If False, leave the rest of the fields empty."
    )
    is_expired: bool = Field(
        default=False,
        description="Whether the event content appears to be expired, outdated, or from a past date. Set to True if the page shows content that is clearly from the past or indicates the event has already occurred."
    )
    description: str = Field(
        description="Extensive, comprehensive information about the main event including (if details are available) the event date, time (in IST), location, cost and any other relevant information.",
        default="",
    )
