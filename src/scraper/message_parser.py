"""Message parser for WhatsApp scraper.

Handles parsing of WhatsApp messages from HTML content, including:
- Text extraction and cleaning
- Image processing from blob URLs
- Date/time parsing and conversion
- Message filtering by event patterns
"""

import re
import random
import time
from datetime import datetime
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup
from playwright.sync_api import Page

from src.scraper.info.events_meta import EVENT_PATTERNS
from src.scraper.info.groups import GROUPS
from .utils.date_handler import convert_whatsapp_date


class MessageParser:
    """Parses WhatsApp messages from HTML content."""

    def __init__(self, page: Page):
        """Initialize parser with Playwright page for image processing.

        Args:
            page: Playwright page instance for accessing blob URLs
        """
        self.page = page
        self._event_pattern = "|".join(EVENT_PATTERNS)

    def parse_messages(
        self, html: str, start_datetime: datetime, group_name: str
    ) -> Dict[str, List[Dict]]:
        """Parse messages from HTML content after start_datetime.

        Args:
            html: HTML content of the WhatsApp chat
            start_datetime: Only include messages after this datetime
            group_name: Name of the WhatsApp group for filtering logic

        Returns:
            Dict where key is "message_num|datetime_str" and value is a list of message parts (text, imgs).
        """
        soup = BeautifulSoup(html, "html.parser")
        messages = {}
        message_num = 0
        current_date = None

        chat_container = soup.find("div", {"role": "application", "data-tab": True})
        if not chat_container:
            raise ValueError("Chat container not found in HTML")

        for div in chat_container.find_all("div", recursive=False):
            # Handle date headers
            if div.has_attr("tabindex"):
                date_span = div.find("span", dir="auto")
                if date_span and date_span.text:
                    current_date = convert_whatsapp_date(date_span.text.strip())
                    continue

            if current_date and current_date >= start_datetime.date():
                try:
                    message_data = self._parse_single_message(div, current_date)
                    if not message_data:
                        continue

                    message_text, images, message_datetime = message_data

                    # Skip if both text and images are empty
                    if not message_text and not images:
                        continue

                    # Apply group-specific filtering
                    if not self._should_include_message(message_text, group_name):
                        continue

                    # Create message entry
                    message_num += 1
                    datetime_str = message_datetime.strftime("%Y-%m-%dT%H:%M%z")
                    key = f"{message_num}|{datetime_str}"

                    messages[key] = [
                        {
                            "text": message_text,
                            "imgs": images,
                        }
                    ]
                except Exception as e:
                    print(f"Error parsing message: {e}")
                    continue

        return messages

    def _parse_single_message(self, div, current_date) -> Optional[tuple]:
        """Parse a single message div element.

        Args:
            div: BeautifulSoup div element containing message
            current_date: Current date for the message

        Returns:
            Tuple of (message_text, images, message_datetime) or None if invalid
        """
        # Try to get the copyable text block
        copyable_text = div.find("div", class_="copyable-text")
        message_text = ""
        time_str = None

        if copyable_text:
            # Extract timestamp from data-pre-plain-text attribute
            pre_text = copyable_text.get("data-pre-plain-text", "")
            time_match = re.search(r"\[(.*?),.*?\]", pre_text)
            if time_match:
                time_str = time_match.group(1).strip()

            # Extract text content if available
            message_content = copyable_text.find("span", class_="selectable-text")
            if message_content:
                message_text = self._extract_text_content(message_content)
        else:
            # For image-only messages, try to extract timestamp from a span matching a time pattern
            timestamp_span = div.find(
                "span",
                text=re.compile(r"\d{1,2}:\d{2}\s*(?:am|pm)", re.IGNORECASE),
            )
            if timestamp_span:
                time_str = timestamp_span.get_text(strip=True)

        # If no timestamp is found, skip this message
        if not time_str:
            return None

        # Parse the time string (assumes format like "7:20 am")
        try:
            message_time = datetime.strptime(time_str, "%I:%M %p").time()
        except Exception:
            return None

        message_datetime = datetime.combine(current_date, message_time)
        message_datetime = message_datetime.replace(tzinfo=ZoneInfo("Asia/Kolkata"))

        # Extract images from the message
        images = self._extract_images(div)

        return message_text, images, message_datetime

    def _extract_text_content(self, message_content) -> str:
        """Extract and clean text content from message element.

        Args:
            message_content: BeautifulSoup element containing message text

        Returns:
            Cleaned message text
        """
        message_text = ""
        for elem in message_content.contents:
            if isinstance(elem, str):
                message_text += elem
            elif elem.name == "br":
                message_text += "\n"
            else:
                message_text += elem.get_text()
        return message_text.strip()

    def _extract_images(self, div) -> Dict[str, str]:
        """Extract images from message div and convert to base64.

        Args:
            div: BeautifulSoup div element containing potential images

        Returns:
            Dict mapping image number (as string) to base64 data
        """
        images = {}
        img_num = 0

        img_tags = div.find_all(
            "img",
            attrs={
                "draggable": True,
                "style": True,
                "src": True,
                "tabindex": False,
            },
        )

        for img in img_tags:
            # Get the Playwright element handle for the <img>
            img_handle = self.page.query_selector(f"img[src='{img.get('src')}']")
            if not img_handle:
                continue

            blob_url = img.get("src")
            if not blob_url:
                continue

            # Skip known placeholders
            if "R0lGODlhAQABAIAAAAAAAP" in blob_url:
                continue

            # Skip tiny images
            style = img.get("style", "").lower()
            if "width:1px" in style or "height:1px" in style:
                continue

            try:
                # Pass the element handle, not the blob_url string
                base64_data = self._get_image_base64(img_handle)
                if base64_data and "R0lGODlhAQABAIAAAAAAAP" not in base64_data:
                    img_num += 1
                    images[str(img_num)] = base64_data
            except Exception as e:
                print(f"Failed to get image data: {e}")

        return images

    def _get_image_base64(self, img_handle) -> str:
        """Get base64 string of image from blob URL using element handle.

        Args:
            img_handle: Playwright element handle for the image

        Returns:
            Base64 encoded image data
        """
        js_code = """
        async (img) => {
            // Use the image element's src attribute (blob URL)
            const url = img.src;

            try {
                // Fetch blob from blob URL inside the same context owning the blob
                const response = await fetch(url);
                if (!response.ok) throw new Error('Failed to fetch blob URL');

                const blob = await response.blob();

                // Convert blob to base64 via FileReader
                const dataUrl = await new Promise((resolve, reject) => {
                    const reader = new FileReader();
                    reader.onloadend = () => resolve(reader.result);
                    reader.onerror = reject;
                    reader.readAsDataURL(blob);
                });
                return dataUrl;

            } catch (err) {
                // If fetch failed, fallback to canvas draw method
                const canvas = document.createElement('canvas');
                canvas.width = img.naturalWidth;
                canvas.height = img.naturalHeight;
                const ctx = canvas.getContext('2d');
                ctx.drawImage(img, 0, 0);
                return canvas.toDataURL();
            }
        }
        """
        # Evaluate the JS code with the element handle
        return self.page.evaluate(js_code, img_handle)

    def _should_include_message(self, message_text: str, group_name: str) -> bool:
        """Determine if message should be included based on group settings and content.

        Args:
            message_text: Text content of the message
            group_name: Name of the WhatsApp group

        Returns:
            True if message should be included, False otherwise
        """
        is_chatty_group = GROUPS.get(group_name, {}).get("chatter", False)

        # For non-chatty groups, include all messages
        if not is_chatty_group:
            return True

        # For chatty groups, only include messages matching event patterns
        return bool(re.search(self._event_pattern, message_text.lower()))
