"""Main WhatsApp scraper orchestrator.

Provides the main WhatsAppScraper class that coordinates browser management,
message parsing, and file operations while maintaining the same public interface
as the original implementation for drop-in replacement compatibility.
"""

import time
import random
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Optional, Dict, List, Set

from playwright.sync_api import TimeoutError

from .browser import BrowserManager
from .message_parser import MessageParser
from .utils.file_handler import MessagesHandler
from .utils.date_handler import convert_whatsapp_date
from src.scraper.info.groups import GROUPS
from src.scraper.info.selectors import SELECTORS


class WhatsAppScraper:
    """Main WhatsApp Web scraper orchestrator.

    Coordinates browser management, message parsing, and file operations
    to provide a clean interface for WhatsApp group scraping operations.
    Maintains compatibility with the original WhatsAppScraper interface.
    """

    def __init__(
        self,
        debugging_port: int = 9222,
        keep_open: bool = False,
        test_run: bool = False,
    ):
        """Initialize the WhatsApp scraper.

        Args:
            debugging_port: Chrome remote debugging port
            keep_open: Keep browser open after operations complete
            test_run: Enable test mode with limited group selection
        """
        # Initialize browser manager
        self.browser_manager = BrowserManager(debugging_port, keep_open, test_run)

        # Initialize message parser (will be set when page is available)
        self.message_parser = None

        # Initialize messages handler
        self.messages_handler = MessagesHandler()

        # Store parameters for compatibility
        self.debugging_port = debugging_port
        self.keep_open = keep_open
        self.test_run = test_run
        self.messages = {}

    @property
    def page(self):
        """Access to browser page for compatibility."""
        return self.browser_manager.page

    @property
    def playwright(self):
        """Access to playwright instance for compatibility."""
        return self.browser_manager.playwright

    @property
    def browser(self):
        """Access to browser instance for compatibility."""
        return self.browser_manager.browser

    @property
    def context(self):
        """Access to browser context for compatibility."""
        return self.browser_manager.context

    def is_port_in_use(self) -> bool:
        """Check if Chrome debugging port is in use."""
        return self.browser_manager.is_port_in_use()

    def start_playwright(self):
        """Start the Playwright instance."""
        self.browser_manager.start_playwright()

    def stop_playwright(self):
        """Stop or disconnect from the browser based on keep_open."""
        self.browser_manager.stop_playwright()

    def initialize(self) -> bool:
        """Initialize persistent browser session and message parser.

        Returns:
            bool: True if initialization successful, False otherwise
        """
        success = self.browser_manager.initialize()
        if success and self.browser_manager.page:
            # Initialize message parser with the page
            self.message_parser = MessageParser(self.browser_manager.page)
        return success

    def wait_for_login(self, timeout: int = 15 * 60) -> bool:
        """Wait for WhatsApp Web login to complete.

        Args:
            timeout: Maximum wait time in seconds

        Returns:
            bool: True if login successful, False if timeout or error
        """
        return self.browser_manager.wait_for_login(timeout)

    def navigate_to_archived(self) -> bool:
        """Navigate to the archived chats page.

        Returns:
            bool: True if navigation successful, False otherwise
        """
        return self.browser_manager.navigate_to_archived()

    def _verify_announcement_group(self, group_name: str) -> bool:
        """Verify if a group has the required Announcements span under any header tag.

        Args:
            group_name: Name of the group to verify

        Returns:
            bool: True if verification passes or not required, False otherwise
        """
        return self.browser_manager._verify_announcement_group(group_name)

    def _wait_for_sync_completion(
        self, max_wait: int = 120, timeout: int = 900
    ) -> bool:
        """Wait for sync message to disappear with exponential backoff.

        Args:
            max_wait: Maximum wait time between checks in seconds
            timeout: Total timeout in seconds

        Returns:
            bool: True if sync completed, False if timed out
        """
        return self.browser_manager._wait_for_sync_completion(max_wait, timeout)

    def scrape_group(
        self,
        group_name: str,
        last_scrape_dt,
        days_back_to_process: int = 10,
        verbose: bool = False,
    ) -> Optional[Dict[str, str]]:
        """Scrape messages from a WhatsApp group.

        Args:
            group_name: Name of the group to scrape
            last_scrape_dt: Last scrape datetime to use as a starting point
            days_back_to_process: Number of days to look back for messages
            verbose: Whether to show sample first and last messages

        Returns:
            Optional[Dict[str, str]]: Messages with datetime as key and text as value, or None if no messages found
        """
        print(f"Scraping group: {group_name}")

        # Wait for sync to complete after selecting chat
        if not self._wait_for_sync_completion():
            print("Warning: Message sync timed out")

        # Get target date from days_back_to_process
        target_date = datetime.now(ZoneInfo("Asia/Kolkata")) - timedelta(
            days=days_back_to_process
        )

        # Use whichever is more recent
        start_datetime_to_scrape = (
            max(target_date, last_scrape_dt) if last_scrape_dt else target_date
        )
        print(
            f"Getting messages from {start_datetime_to_scrape.date()}.\nLast file scrape date: {last_scrape_dt.date()}"
        )

        # Look for scroll to bottom button and click if present
        scroll_button = self.page.locator(SELECTORS["CHAT_SCROLL_BOTTOM_BUTTON"]).first
        if scroll_button.is_visible():
            print("Found scroll to bottom button, clicking...")
            scroll_button.click()
            time.sleep(3)  # Wait for scrolling to complete

        # Get the chat scroll container
        scroll_container = self.page.locator(SELECTORS["CHAT_SCROLL_CONTAINER"]).first

        def check_target_date():
            """Check if target date is in current view."""
            date_divs = self.page.locator(SELECTORS["MESSAGE_DATE_DIVS"]).all()
            oldest_date = None

            for div in date_divs:
                try:
                    if div.is_visible():
                        date_text = div.text_content().strip()
                        parsed_date = convert_whatsapp_date(date_text)
                        if parsed_date:
                            if oldest_date is None or parsed_date < oldest_date:
                                oldest_date = parsed_date
                                if parsed_date <= start_datetime_to_scrape.date():
                                    print(f"Found target date: {parsed_date}")
                                    return True
                except Exception as e:
                    print(f"Failed to parse date: {e}")

            return False

        def most_recent_date():
            """Get the most recent date in the current view."""
            date_divs = self.page.locator(SELECTORS["MESSAGE_DATE_DIVS"]).all()
            most_recent = None

            for div in date_divs:
                try:
                    if div.is_visible():
                        date_text = div.text_content().strip()
                        parsed_date = convert_whatsapp_date(date_text)
                        if parsed_date:
                            if most_recent is None or parsed_date > most_recent:
                                most_recent = parsed_date
                except Exception as e:
                    print(f"Failed to parse date: {e}")

            return most_recent

        # Scroll up until target date is found
        target_found = False
        no_scroll_count = 0
        skip_check = False
        while not target_found:
            # Check current view for target date
            target_found = check_target_date()
            if target_found:
                break

            check_on_phone_message = self.page.locator(
                SELECTORS["USE_PHONE_MESSAGE"]
            ).first
            sync_paused_message = self.page.locator(
                SELECTORS["SYNC_PAUSED_MESSAGE"]
            ).first

            if check_on_phone_message.is_visible() and not skip_check:
                user_input = (
                    input(
                        f"WhatsApp Web is asking to 'Use phone' for group {group_name}. Do you want to continue? (y/n): "
                    )
                    .strip()
                    .lower()
                )
                if user_input not in ["y", "yes"]:
                    raise ValueError(
                        f"User chose to stop. WhatsApp Web showing 'Use phone' message for group {group_name}."
                    )
                else:
                    skip_check = True
                print(
                    f"Continuing scraping for group {group_name} despite 'Use phone' message..."
                )

            if sync_paused_message.is_visible():
                raise ValueError(
                    f"Whatsapp Web sync is paused for group {group_name}. Sync paused message is visible."
                )

            if not self._wait_for_sync_completion():
                raise ValueError(
                    f"Sync timed out while scraping {group_name}. Please try again later."
                )

            # Check for older messages button
            older_messages = self.page.locator(SELECTORS["OLDER_MESSAGES_BUTTON"]).first
            if older_messages.is_visible():
                print("Loading older messages...")
                older_messages.click()
                time.sleep(1)
                continue

            # Scroll to top
            current_scroll = scroll_container.evaluate("el => el.scrollTop")
            scroll_container.evaluate("el => el.scrollTop = 0")
            new_scroll = scroll_container.evaluate("el => el.scrollTop")

            if current_scroll == new_scroll:
                no_scroll_count += 1
                if no_scroll_count > 3:
                    print("Reached the top of the chat")
                    break
                else:
                    continue

            time.sleep(2)  # Wait for content to load

        if target_found:
            # Handle all "Read more" buttons
            print("Expanding all 'Read more' messages...")
            while True:
                read_more_buttons = self.page.locator(
                    SELECTORS["READ_MORE_BUTTON"]
                ).all()
                if not read_more_buttons:
                    break

                clicked = False
                for button in read_more_buttons:
                    try:
                        if button.is_visible():
                            button.scroll_into_view_if_needed(timeout=5000)
                            time.sleep(0.5)

                            if button.is_visible():
                                button.click()
                                clicked = True
                                time.sleep(0.5)  # Wait for expansion
                    except Exception as e:
                        print(f"Failed to click read more button: {e}")

                if not clicked:
                    break

            # Parse messages using the message parser
            print("Parsing messages...")
            html = self.page.content()
            messages = self.message_parser.parse_messages(
                html, start_datetime_to_scrape, group_name
            )

            if messages:
                print(f"{group_name} completed: {len(messages)} messages scraped")
                print("-" * 40)
                return messages

            print(f"{group_name} completed: 0 messages scraped")
            print("-" * 40)
            return None

    def find_groups(self, groups_list: List[str], days_back: int = 7) -> Set[str]:
        """Find specified groups in the archived chats.

        Args:
            groups_list: List of group names to search for
            days_back: Number of days to look back for messages

        Returns:
            Set of found group names
        """
        # If test_run is True, use limited group selection
        if self.test_run:
            groups_list = ["BLR Events Hub"]

        if not self.navigate_to_archived():
            print("Could not access archived chats")
            return set()

        scroll_container = self.page.locator(SELECTORS["SCROLL_CONTAINER"]).first

        # Scroll to top first
        print("Scrolling to top of archived chats...")
        scroll_container.evaluate("el => el.scrollTop = 0")
        time.sleep(2)  # Wait for content to load

        found_groups = set()
        remaining_groups = set(groups_list)  # Track unfound groups
        groups_data = []  # Store all group data for messages.json
        last_scroll_position = 0
        start_time = time.time()
        timeout = 30 * 60  # 30 minutes timeout

        last_scrape_dt = self.messages_handler.get_last_scrape_datetime()

        # Get container height and calculate fixed scroll amount (70%)
        container_height = scroll_container.evaluate("el => el.clientHeight")
        scroll_amount = int(container_height * 0.7)

        while len(found_groups) < len(groups_list):
            if time.time() - start_time > timeout:
                print("Stopped due to timeout (30 minutes)")
                break

            # Process visible groups
            group_elements = self.page.locator(SELECTORS["ARCHIVED_GROUPS"]).all()

            # Check each visible group
            for element in group_elements:
                try:
                    group_name = element.text_content(timeout=5 * 1000)
                except TimeoutError as e:
                    print(f"Timeout while getting group name: {e}")
                    break
                # Check if any name in remaining_groups is contained within this group name
                matching_groups = [
                    g for g in remaining_groups if g.lower() in group_name.lower()
                ]
                if matching_groups:
                    if len(matching_groups) > 1:
                        raise Exception(
                            f"Error: Imprecise group name in group list for {group_name}. Multiple matches: {matching_groups}"
                        )

                    matched_group = matching_groups[0]
                    if group_name not in found_groups:
                        print(f"Found group: {group_name} (matched: {matched_group})")
                        element.click()
                        time.sleep(2)  # Wait for group to load

                        # Wait for sync to complete after clicking group
                        if not self._wait_for_sync_completion():
                            print(
                                f"Warning: Message sync timed out for {matched_group}"
                            )
                            continue

                        # Verify announcement group if needed
                        if not self._verify_announcement_group(matched_group):
                            print(
                                f"Skipping {matched_group}: Not the announcement group we're looking for"
                            )
                            continue

                        if messages := self.scrape_group(
                            matched_group, last_scrape_dt, days_back
                        ):
                            # Add group data with messages
                            group_data = {
                                "group_name": matched_group,
                                "created_at": datetime.now(
                                    ZoneInfo("Asia/Kolkata")
                                ).strftime("%Y-%m-%dT%H:%M%z"),
                                "messages": messages,
                            }
                            groups_data.append(group_data)

                        found_groups.add(group_name)
                        remaining_groups.remove(matched_group)

                        print(f"Groups remaining: {len(remaining_groups)}")
                        if len(remaining_groups) == 0:
                            print("All groups found!")
                            break
                        elif len(remaining_groups) < 3:
                            print(f"Remaining groups: {remaining_groups}")

            # Calculate new scroll position
            new_scroll_position = last_scroll_position + scroll_amount
            current_scroll_height = scroll_container.evaluate("el => el.scrollHeight")

            # Check if we've reached the bottom
            if (
                new_scroll_position >= current_scroll_height
                or new_scroll_position <= last_scroll_position
            ):
                print("Reached end of archived chats")
                break

            # Perform the scroll
            scroll_container.evaluate(f"el => el.scrollTop = {new_scroll_position}")
            current_position = scroll_container.evaluate("el => el.scrollTop")

            if current_position == last_scroll_position:
                print("Reached end of archived chats")
                break

            last_scroll_position = current_position

            # Wait for content to load
            time.sleep(1)

        # After processing all groups, create the messages file
        if groups_data:
            self.messages_handler.create_messages_file(groups_data)
            print(f"Created messages file with {len(groups_data)} groups")

        print(f"Found {len(found_groups)} out of {len(groups_list)} groups")
        if remaining_groups:
            print(f"Groups not found: {remaining_groups}")
        return found_groups

    def run(self, groups_list: List[str], days_back: int = 7) -> bool:
        """Main entry point to run the scraper.

        Args:
            groups_list: List of group names to scrape
            days_back: Number of days to look back for messages

        Returns:
            bool: True if operation completed successfully
        """
        try:
            self.start_playwright()

            if not self.initialize():
                print("Failed to initialize browser")
                return False

            if not self.wait_for_login():
                print("Failed to login to WhatsApp Web")
                return False

            found_groups = self.find_groups(groups_list, days_back)
            print(f"Scraping completed. Found {len(found_groups)} groups.")
            return True

        except Exception as e:
            print(f"Error during scraping: {e}")
            return False
        finally:
            self.stop_playwright()
