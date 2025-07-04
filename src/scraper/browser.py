"""Browser automation manager for WhatsApp Web scraping.

This module provides clean browser session management, authentication handling,
and navigation capabilities for WhatsApp Web automation using Playwright.
"""

from playwright.sync_api import sync_playwright, Page, Browser, TimeoutError
from typing import Optional
import socket
import os
import time
import re
from src.scraper.info.selectors import SELECTORS
from config.config import CHROME_PROFILE_DIR


class BrowserManager:
    """Manages browser automation for WhatsApp Web scraping.

    Handles browser initialization, session management, authentication,
    and navigation with minimal complexity.
    """

    def __init__(
        self,
        debugging_port: int = 9222,
        keep_open: bool = False,
        test_run: bool = False,
    ):
        """Initialize browser manager.

        Args:
            debugging_port: Chrome remote debugging port
            keep_open: Keep browser open after operations
            test_run: Enable test mode functionality
        """
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None
        self.debugging_port = debugging_port
        self.keep_open = keep_open
        self.test_run = test_run

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

        Returns:
            bool: True if initialization successful, False otherwise
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
            else:
                # Use configured profile directory for browser data
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

    def _validate_storage_state(self, storage_state: dict) -> bool:
        """Validate storage state contains required WhatsApp Web data.

        Args:
            storage_state: Storage state dictionary to validate

        Returns:
            bool: True if valid, False otherwise
        """
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

    def wait_for_login(self, timeout: int = 15 * 60) -> bool:
        """Wait for WhatsApp Web login to complete.

        Args:
            timeout: Maximum wait time in seconds

        Returns:
            bool: True if login successful, False if timeout or error
        """
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
        """Check if messages are loading and return percentage if found.

        Returns:
            Percentage loaded if on loading page, None otherwise
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
        """Calculate wait time based on loading progress.

        Args:
            current_percentage: Current loading percentage
            last_percentage: Previous loading percentage
            last_wait_time: Previous wait time

        Returns:
            Calculated wait time in seconds
        """
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

    def navigate_to_archived(self) -> bool:
        """Navigate to the archived chats page.

        Returns:
            bool: True if navigation successful, False otherwise
        """
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

    def _verify_announcement_group(self, group_name: str) -> bool:
        """Verify if a group has the required Announcements span under any header tag.

        Args:
            group_name: Name of the group to verify

        Returns:
            bool: True if verification passes or not required, False otherwise
        """
        # Import here to avoid circular import
        from config import GROUPS

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
