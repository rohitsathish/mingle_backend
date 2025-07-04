# %%
from playwright.sync_api import sync_playwright, Page, Browser, TimeoutError
from typing import Optional, Dict, List, Tuple
from src.scraper.messages_handler import MessagesHandler
import json
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import time
import socket
import os
import re
import random


from config import GROUPS, MESSAGES_JSON_PATH, SELECTORS, CHROME_PROFILE_DIR
from src.scraper.utils.date_handler import convert_whatsapp_date
from src.scraper.message_parser import MessageParser


class WhatsAppScraper:
    """WhatsApp Web scraper using Playwright."""

    def _verify_announcement_group(self, group_name: str) -> bool:
        """Verify if a group has the required Announcements span under any header tag.

        Args:
            group_name: Name of the group to verify

        Returns:
            bool: True if verification passes or not required, False otherwise
        """
        # Check if this group requires announcement verification
        group_config = GROUPS.get(group_name, {})
        if not group_config.get("announce_gp", False):
            return True  # No verification needed

        try:
            # Look for any header that has a descendant span with title="Announcements"
            announcement_span = self.page.locator(
                'header span[title="Announcements"]'
            ).first
            return announcement_span.is_visible()
        except Exception as e:
            print(f"Error verifying announcement group: {e}")
            return False

    def __init__(
        self,
        debugging_port: int = 9222,
        keep_open: bool = False,
        test_run: bool = False,
    ):
        """Initialize the WhatsApp scraper."""
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None
        self.messages = {}
        self.debugging_port = debugging_port
        self.keep_open = keep_open
        self.test_run = test_run
        # Initialize messages handler
        self.messages_handler = MessagesHandler()
        # Initialize message parser (will be set when page is available)
        self.message_parser = None

    def is_port_in_use(self) -> bool:
        """Check if Chrome debugging port is in use."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            return s.connect_ex(("127.0.0.1", self.debugging_port)) == 0

    def start_playwright(self):
        """Start the Playwright instance."""
        self.playwright = sync_playwright().start()

    def stop_playwright(self):
        """Stop or disconnect from the browser based on keep_open."""
        if self.keep_open:
            print("Browser will remain open. Press Enter to close...")
            input()

        # Fully close the browser & Playwright
        if self.context:
            self.context.close()
        if self.browser:
            self.browser.close()
        if self.playwright:
            self.playwright.stop()
        print("Browser fully closed and Playwright stopped")

    def initialize(self) -> bool:
        """Initialize persistent browser session using a dedicated profile.
        Retains an existing session if the debugging port is in use.
        """
        try:
            if self.is_port_in_use():
                print(
                    f"Connecting to existing Chrome session on port {self.debugging_port}"
                )
                self.browser = self.playwright.chromium.connect_over_cdp(
                    f"http://localhost:{self.debugging_port}"
                )
                self.context = self.browser.contexts[0]
                self.page = self.context.pages[0]

                # Initialize message parser with page
                self.message_parser = MessageParser(self.page)
            else:
                # Define a persistent profile folder to store all browser data
                profile_dir = str(CHROME_PROFILE_DIR)
                print("Starting persistent Chrome session using profile:", profile_dir)

                # Launch a persistent context with flags to reduce stored data
                self.browser = self.playwright.chromium.launch_persistent_context(
                    profile_dir,
                    headless=False,
                    viewport=None,
                    args=[
                        f"--remote-debugging-port={self.debugging_port}",
                        "--disk-cache-size=0",  # Disable disk caching
                        "--disable-application-cache",  # Disable the application cache
                        "--disable-sync",  # Turn off profile syncing
                        "--disable-extensions",  # Prevent extensions from being loaded
                        "--no-sandbox",
                        "--start-maximized",  # Start maximized
                        "--disable-gpu",  # Disable GPU hardware acceleration
                    ],
                )

                # Use the first page if available, otherwise create a new one.
                if self.browser.pages:
                    self.page = self.browser.pages[0]
                else:
                    self.page = self.browser.new_page()

                # Initialize message parser with page
                self.message_parser = MessageParser(self.page)

                try:
                    cdp = self.page.context.new_cdp_session(self.page)
                    window_info = cdp.send("Browser.getWindowForTarget")
                    cdp.send(
                        "Browser.setWindowBounds",
                        {
                            "windowId": window_info["windowId"],
                            "bounds": {"windowState": "maximized"},
                        },
                    )
                except Exception as e:
                    print(f"Failed to maximize window using CDP: {e}")

                # Navigate to WhatsApp Web if not already there
                if not self.page.url or "web.whatsapp.com" not in self.page.url:
                    self.page.goto(
                        "https://web.whatsapp.com", wait_until="domcontentloaded"
                    )
            return True
        except Exception as e:
            print(f"Failed to initialize browser: {e}")
            return False

    def _is_qr_code_page(self) -> bool:
        """Check if currently on QR code page."""
        try:

            has_scan_text = self.page.locator("text=scan the QR code").is_visible()
            has_login_text = self.page.locator(
                "text='Log into WhatsApp Web'"
            ).is_visible()
            return has_scan_text and has_login_text
        except:
            return False

    def _is_loading_messages(self) -> Optional[int]:
        """
        Check if messages are loading and return percentage if found.
        Returns: Percentage loaded if on loading page, None otherwise.
        """
        try:
            loading_text = self.page.locator(
                "text=Loading your chats"
            ).first.text_content()
            if "Don't close this window" in self.page.content():
                # Extract percentage from "Loading your chats [xx%]"
                if match := re.search(r"\[(\d+)%\]", loading_text):
                    return int(match.group(1))
        except:
            pass
        return None

    def _calculate_wait_time(
        self, current_percentage: int, last_percentage: int, last_wait_time: float
    ) -> float:
        """Calculate wait time based on loading progress."""
        if current_percentage <= last_percentage:
            # If progress is stuck, increase wait time
            return min(last_wait_time * 1.5, 10.0)  # Cap at 10 seconds
        else:
            # Progress is being made, adjust wait time based on speed
            progress_rate = current_percentage - last_percentage
            if progress_rate > 20:
                return 1.0  # Fast progress, check quickly
            elif progress_rate > 10:
                return 2.0  # Moderate progress
            else:
                return 3.0  # Slow progress

    def _is_end_to_end_encrypted(self) -> bool:
        """Check if end-to-end encryption notice is visible."""
        try:
            return "End-to-end encrypted" in self.page.content()
        except:
            return False

    def _validate_storage_state(self, storage_state: dict) -> bool:
        """Validate storage state contains required WhatsApp Web data."""
        try:
            # Basic structure check
            if not isinstance(storage_state, dict):
                print("Storage state is not a dictionary")
                return False

            # Check cookies
            cookies = storage_state.get("cookies", [])
            if not isinstance(cookies, list):
                print("Cookies is not a list")
                return False

            # Verify essential WhatsApp cookies
            wa_cookies = {
                cookie["name"]: cookie
                for cookie in cookies
                if cookie.get("domain", "").endswith("web.whatsapp.com")
            }
            if "wa_ul" not in wa_cookies:
                print("Missing essential WhatsApp cookie: wa_ul")
                return False

            # Check origins
            origins = storage_state.get("origins", [])
            if not isinstance(origins, list):
                print("Origins is not a list")
                return False

            # Look for WhatsApp Web origin
            for origin in origins:
                if origin.get("origin") == "https://web.whatsapp.com":
                    return True

            print("No WhatsApp Web origin found")
            return False
        except Exception as e:
            print(f"Storage state validation failed: {e}")
            return False

    def _wait_for_sync_completion(
        self, max_wait: int = 120, timeout: int = 900
    ) -> bool:
        """Wait for sync message to disappear with exponential backoff.

        Args:
            max_wait: Maximum wait time between checks in seconds (default 120)
            timeout: Total timeout in seconds (default 600)
        Returns:
            bool: True if sync completed, False if timed out
        """
        base_wait = 1
        current_wait = base_wait
        start_time = time.time()

        while time.time() - start_time < timeout:
            try:
                sync_message = self.page.locator(
                    SELECTORS["SYNC_PROGRESS_MESSAGE"]
                ).first
                if not sync_message.is_visible():
                    return True

                print(f"Waiting for message sync... (next check in {current_wait}s)")
                time.sleep(current_wait)

                # Exponential backoff with max cap
                current_wait = min(current_wait * 2, max_wait)

            except Exception as e:
                print(f"Error checking sync status: {e}")
                return True  # Assume sync completed if we can't find the message

        print(f"Sync wait timed out after {timeout} seconds")
        return False

    def wait_for_login(self, timeout: int = 15 * 60) -> bool:
        """Wait for WhatsApp Web login to complete."""
        try:
            start_time = time.time()
            last_percentage = 0
            wait_time = 1
            retry_num = 0

            while time.time() - start_time < timeout:
                # Check if already on chat list
                if self.page.locator(SELECTORS["MAIN_PAGE_HEADER"]).is_visible(
                    timeout=100
                ):
                    print("Chat list is visible!")

                    # Wait for service worker and IndexedDB to be ready
                    time.sleep(3)

                    if self.keep_open:
                        print("Browser will remain open")
                    return True

                # Check for QR code page
                if self._is_qr_code_page():
                    print("Please scan the QR code with your phone...")
                    input("Press Enter after scanning the QR code...")
                    continue

                # Check for loading page
                if current_percentage := self._is_loading_messages():
                    print(f"Loading messages: {current_percentage}%")
                    wait_time = self._calculate_wait_time(
                        current_percentage, last_percentage, wait_time
                    )
                    last_percentage = current_percentage
                    time.sleep(wait_time)
                    continue

                # Check for end-to-end encrypted message
                if self._is_end_to_end_encrypted():
                    print("Waiting for chats to load...")
                    time.sleep(2)
                    continue

                # If none of the above cases match, we're on an unrecognized page
                if retry_num > 3:
                    print("Unrecognized Page, script is halted")
                    return False

                retry_num += 1
                time.sleep(1)

            print("Login timed out!")
            return False
        except Exception as e:
            print(f"Login failed: {e}")
            return False

    def navigate_to_archived(self) -> bool:
        """Navigate to the archived chats page."""
        # First check if we're already on the archived page
        if self.page.locator(SELECTORS["ARCHIVED_HEADER"]).is_visible(timeout=1000):
            print("Already on archived chats page")
            return True

        # Wait for the chat list and click the Archived link
        self.page.wait_for_selector(SELECTORS["MAIN_PAGE_HEADER"], timeout=10000)
        archived_link = self.page.locator(SELECTORS["ARCHIVED_TEXT"]).first

        if not archived_link.is_visible():
            print("Could not find Archived link")
            return False

        archived_link.click()

        # Wait for archived header to confirm we're on archived page
        self.page.wait_for_selector(SELECTORS["ARCHIVED_HEADER"], timeout=5000)
        print("Successfully navigated to archived chats")
        return True

    # def get_image_base64(self, page, blob_url: str) -> str:
    #     """Get base64 string of image from blob URL with multiple fallback methods."""

    #     js_code = """
    #     async (url) => {
    #         // Primary method: fetch blob and convert via FileReader
    #         try {
    #             const response = await fetch(url);
    #             if (!response.ok) throw new Error('Network response was not ok');
    #             const blob = await response.blob();
    #             const reader = new FileReader();
    #             const dataUrl = await new Promise((resolve, reject) => {
    #                 reader.onloadend = () => resolve(reader.result);
    #                 reader.onerror = reject;
    #                 reader.readAsDataURL(blob);
    #             });
    #             return dataUrl;
    #         } catch (primaryError) {
    #             // Fallback 1: draw image on canvas and export
    #             try {
    #                 const img = new Image();
    #                 img.src = url;
    #                 await new Promise((res, rej) => {
    #                     img.onload = res;
    #                     img.onerror = rej;
    #                 });
    #                 const canvas = document.createElement('canvas');
    #                 canvas.width = img.naturalWidth;
    #                 canvas.height = img.naturalHeight;
    #                 const ctx = canvas.getContext('2d');
    #                 ctx.drawImage(img, 0, 0);
    #                 return canvas.toDataURL();
    #             } catch (canvasError) {
    #                 // Fallback 2: XHR method
    #                 return new Promise((resolve, reject) => {
    #                     const xhr = new XMLHttpRequest();
    #                     xhr.open('GET', url);
    #                     xhr.responseType = 'blob';
    #                     xhr.onload = () => {
    #                         const reader = new FileReader();
    #                         reader.onloadend = () => resolve(reader.result);
    #                         reader.onerror = reject;
    #                         reader.readAsDataURL(xhr.response);
    #                     };
    #                     xhr.onerror = () => reject(new Error('XHR failed'));
    #                     xhr.send();
    #                 });
    #             }
    #         }
    #     }
    #     """

    #     # Implement retry logic
    #     max_retries = 3
    #     retry_count = 0
    #     last_error = None

    #     while retry_count < max_retries:
    #         try:
    #             result = page.evaluate(js_code, blob_url)
    #             break  # Success, exit the retry loop
    #         except Exception as e:
    #             retry_count += 1
    #             last_error = e
    #             print(f"Image fetch attempt {retry_count} failed: {e}")
    #             if retry_count < max_retries:
    #                 # Add exponential backoff with jitter
    #                 wait_time = min(2 ** retry_count * 0.5, 2) + random.random()
    #                 print(f"Retrying in {wait_time:.2f} seconds...")
    #                 time.sleep(wait_time)

    #     # If we've exhausted all retries, raise the last error
    #     if retry_count == max_retries:
    #         raise Exception(f"Failed to fetch image after {max_retries} attempts: {last_error}")

    #     # Check for known placeholder signature (1x1 transparent GIF)
    #     if result.startswith("data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP"):
    #         raise Exception("Returned image appears to be a placeholder")
    #     return result

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
            f"Getting messages from {start_datetime_to_scrape.date()}. \n Last file scrape date: {last_scrape_dt.date()}"
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

            # Parse messages
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

    def find_groups(self, groups_list: List[str], days_back: int = 7) -> set:
        """Find specified groups in the archived chats.

        Args:
            groups_list: List of group names to search for
            days_back: Number of days to look back for messages

        Returns:
            Set of found group names
        """
        # If test_run is True, randomly select 3 groups
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
