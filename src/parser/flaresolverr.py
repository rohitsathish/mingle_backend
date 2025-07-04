"""Flaresolverr client for Cloudflare bypass.

Provides async client for interacting with Flaresolverr service
for bypassing Cloudflare protection when crawling URLs.
"""

import asyncio
import hashlib
import os
import random
import time
from typing import Dict, List, Optional, Tuple

import httpx
import requests
from httpx import BasicAuth
from requests.auth import HTTPBasicAuth
from src.parser.api import HTTPX_CLIENT, cache

# Setup logging using centralized config
from config.logs import get_logger
logger = get_logger(__name__)


class AsyncFlaresolverrClient:
    """Async Python client for interacting with a Flaresolverr instance.

    Manages session creation, requests, and destruction with robust session management.
    """

    def __init__(self, flaresolverr_url: str = "http://localhost:8191/v1", 
                 use_auth: bool = False, username: str = "", password: str = ""):
        """Initialize the client.

        Args:
            flaresolverr_url: The base URL of the Flaresolverr API.
            use_auth: Whether to use HTTP Basic Authentication.
            username: Username for authentication.
            password: Password for authentication.
        """
        self.base_url = flaresolverr_url
        self.use_auth = use_auth
        self.username = username
        self.password = password
        self.auth = BasicAuth(username, password) if use_auth and username and password else None
        self.active_sessions: Dict[str, str] = {}
        self._health_checked = False

    def ensure_service_ready_sync(self) -> None:
        """Ensure Flaresolverr service is ready with up to 2 health checks (sync version).
        
        Performs up to 2 health checks with 5s gap to handle cold starts.
        Raises exception if service is not responsive after both attempts.
        """
        if self._health_checked:
            return
            
        logger.info("Checking Flaresolverr service readiness...")
        
        for attempt in range(1, 4):  # 3 attempts
            try:
                response = requests.post(
                    self.base_url,
                    json={"cmd": "sessions.list"},
                    timeout=30,  # Generous timeout for cold start
                    auth=HTTPBasicAuth(self.username, self.password) if self.use_auth and self.username and self.password else None
                )
                
                if response.status_code == 200:
                    logger.info(f"Flaresolverr ready (attempt {attempt})")
                    self._health_checked = True
                    return
                else:
                    logger.warning(f"Health check attempt {attempt} failed: HTTP {response.status_code}")
                    
            except Exception as e:
                logger.warning(f"Health check attempt {attempt} failed: {e}")

            wait_time = min(20 * attempt, 30)  # Exponential backoff (20s, 30s, 40s)
            logger.info(f"Waiting {wait_time}s before retry...")
            time.sleep(wait_time)

        self._health_checked = True  # Don't retry in same session
        raise ValueError("Flaresolverr service not responsive after 3 health checks")

    def get_session_failures(self, session_id: str) -> List[bool]:
        """Get session failure history from unified cache."""
        try:
            return cache.get(f"flaresolverr:failures:{session_id}", [])
        except Exception as e:
            logger.warning(f"Could not load session failures for {session_id}: {e}")
            return []

    def save_session_failures(self, session_id: str, failures: List[bool]):
        """Save session failure history to unified cache with no expiry."""
        try:
            # Store with no expiry (None) for persistence across restarts
            cache.set(f"flaresolverr:failures:{session_id}", failures, expire=None)
        except Exception as e:
            logger.warning(f"Could not save session failures for {session_id}: {e}")

    def record_session_result(self, session_id: str, success: bool):
        """Record the result of a session attempt."""
        # Get existing failures or empty list
        failures = self.get_session_failures(session_id)
        
        # Add result and keep only last 5 attempts
        failures.append(success)
        failures = failures[-5:]
        
        # Save to diskcache with no expiry for persistence
        self.save_session_failures(session_id, failures)

    def is_session_retired(self, session_id: str) -> bool:
        """Check if a session should be retired (5 consecutive failures)."""
        failures = self.get_session_failures(session_id)
        
        # Check if we have 5 attempts and all are failures
        return len(failures) >= 5 and not any(failures)

    def get_active_session_ids(self) -> List[str]:
        """Get list of session IDs that are not retired.
        
        Checks sessions starting from flare_session_1 onwards until we find
        two non-retired sessions, creating new ones as necessary.
        """
        active_sessions = []
        session_num = 1
        
        # Check existing sessions starting from 1 until we have 2 active ones
        while len(active_sessions) < 2:
            session_id = f"flare_session_{session_num}"
            
            if not self.is_session_retired(session_id):
                active_sessions.append(session_id)
            
            session_num += 1
            
            # Safety check to prevent infinite loop (max 100 sessions to check)
            if session_num > 100:
                # If we somehow have 100 retired sessions, reset and create new ones
                logger.warning("Reached maximum session check limit, creating fresh sessions")
                while len(active_sessions) < 2:
                    session_num += 1
                    active_sessions.append(f"flare_session_{session_num}")
                break
        
        return active_sessions[:2]  # Always return exactly 2 sessions

    def get_url_pathways(self, url: str) -> List[Tuple[Optional[str], int]]:
        """Get the 4 pathways for URL processing.

        2 tracked sessions + 1 unique URL session + 1 no-session.
        Each pathway is tried twice. No-session is tried last as a fallback.

        Returns:
            List of tuples (session_id, attempt_number) for each pathway
        """
        pathways = []

        # Pathways 1-2: Active tracked sessions (2 attempts each)
        active_sessions = self.get_active_session_ids()
        for session_id in active_sessions[:2]:  # Only use first 2 active sessions
            pathways.extend([(session_id, 1), (session_id, 2)])

        # Pathway 3: Unique URL-specific session (2 attempts) - NOT tracked for failures
        url_hash = hashlib.md5(url.encode()).hexdigest()[:8]
        unique_session_id = f"flare_url_{url_hash}"
        pathways.extend([(unique_session_id, 1), (unique_session_id, 2)])

        # Pathway 4: No session (2 attempts) - as last resort
        pathways.extend([(None, 1), (None, 2)])

        return pathways

    def create_session_sync(self, session_id: str) -> bool:
        """Synchronously create a new browser session in Flaresolverr.

        Args:
            session_id: A unique name for the session.

        Returns:
            True if the session was created successfully, False otherwise.
        """
        logger.info(f"Creating Flaresolverr session (sync): {session_id}")
        payload = {"cmd": "sessions.create", "session": session_id}

        try:
            response = requests.post(self.base_url, json=payload, timeout=30, auth=HTTPBasicAuth(self.username, self.password) if self.use_auth and self.username and self.password else None)
            response.raise_for_status()
            data = response.json()

            if data.get("status") == "ok":
                self.active_sessions[session_id] = session_id
                logger.info(f"Session '{session_id}' created successfully")
                return True
            else:
                logger.error(f"Error creating session: {data.get('message')}")
                return False

        except requests.RequestException as e:
            logger.error(f"Failed to connect to Flaresolverr: {e}")
            return False

    def get_url_sync(
        self,
        url: str,
        session_id: Optional[str] = None,
        timeout_ms: int = 180000,
        use_cache: bool = True,
    ) -> Optional[str]:
        """Synchronously fetch a URL using robust session management.

        This method implements 4 pathways:
        1. No session (2 attempts)
        2-4. Three tracked sessions (2 attempts each)

        Sessions are automatically retired after 5 consecutive failures.

        Args:
            url: The URL to fetch.
            session_id: Legacy parameter - ignored in favor of automatic session management.
            timeout_ms: Timeout for the request in milliseconds.
            use_cache: Whether to use cached results if available.

        Returns:
            The HTML content of the page as a string, or None if all pathways failed.
        """
        # Check cache first
        if use_cache:
            cache_key = f"flaresolverr:url:{url}"
            cached = cache.get(cache_key)
            if cached is not None:
                return cached

        # Ensure service is ready before making requests
        self.ensure_service_ready_sync()

        pathways = self.get_url_pathways(url)
        last_error = None

        for i, (pathway_session_id, attempt_num) in enumerate(pathways):
            try:
                # Create session if it doesn't exist and is not None
                if (
                    pathway_session_id
                    and pathway_session_id not in self.active_sessions
                ):
                    success = self.create_session_sync(pathway_session_id)
                    if not success:
                        logger.warning(
                            f"Failed to create session {pathway_session_id}, skipping"
                        )
                        continue

                # Build payload
                payload = {"cmd": "request.get", "url": url, "maxTimeout": timeout_ms}
                if pathway_session_id and pathway_session_id in self.active_sessions:
                    payload["session"] = pathway_session_id

                # Make request
                response = requests.post(
                    self.base_url, json=payload, timeout=(timeout_ms / 1000) + 10, auth=HTTPBasicAuth(self.username, self.password) if self.use_auth and self.username and self.password else None
                )
                response.raise_for_status()
                data = response.json()

                if data.get("status") == "ok":
                    html_content = data["solution"]["response"]

                    # Check for Cloudflare challenges
                    if any(
                        challenge in html_content
                        for challenge in [
                            "https://challenges.cloudflare.com/cdn-cgi/",
                            "/cdn-cgi/styles/cf.errors.css",
                        ]
                    ):
                        # Only record failures for tracked sessions (not URL-specific ones)
                        if pathway_session_id and not pathway_session_id.startswith(
                            "flare_url_"
                        ):
                            self.record_session_result(pathway_session_id, False)
                        last_error = "Cloudflare challenge still present"
                        continue

                    # Success!
                    # Only record success for tracked sessions (not URL-specific ones)
                    if pathway_session_id and not pathway_session_id.startswith(
                        "flare_url_"
                    ):
                        self.record_session_result(pathway_session_id, True)

                    # Cache successful result
                    if use_cache:
                        cache_key = f"flaresolverr:url:{url}"
                        cache.set(
                            cache_key, html_content, expire=60 * 60 * 24 * 3
                        )  # 3 days expiry

                    return html_content
                else:
                    error_msg = data.get("message", "Unknown error")
                    # Only record failures for tracked sessions (not URL-specific ones)
                    if pathway_session_id and not pathway_session_id.startswith(
                        "flare_url_"
                    ):
                        self.record_session_result(pathway_session_id, False)
                    last_error = error_msg

            except requests.RequestException as e:
                # Only record failures for tracked sessions (not URL-specific ones)
                if pathway_session_id and not pathway_session_id.startswith(
                    "flare_url_"
                ):
                    self.record_session_result(pathway_session_id, False)
                last_error = str(e)

            except Exception as e:
                logger.warning(
                    f"Unexpected error for {url} with {'no session' if not pathway_session_id else pathway_session_id}: {e}"
                )
                # Only record failures for tracked sessions (not URL-specific ones)
                if pathway_session_id and not pathway_session_id.startswith(
                    "flare_url_"
                ):
                    self.record_session_result(pathway_session_id, False)
                last_error = str(e)

            # Add delay between attempts (except for last attempt)
            if i < len(pathways) - 1:
                time.sleep(random.uniform(3.0, 5.0))

        logger.error(f"All pathways failed for {url}. Last error: {last_error}")
        return None

    async def destroy_session(self, session_id: str) -> bool:
        """Destroy a browser session in Flaresolverr.

        Args:
            session_id: The name of the session to destroy.

        Returns:
            True if successful, False otherwise.
        """
        if session_id not in self.active_sessions:
            logger.warning(f"Session '{session_id}' not found")
            return False

        logger.info(f"Destroying Flaresolverr session: {session_id}")
        payload = {"cmd": "sessions.destroy", "session": session_id}

        try:
            response = await HTTPX_CLIENT.post(self.base_url, json=payload, timeout=30, auth=self.auth)
            response.raise_for_status()
            data = response.json()

            if data.get("status") == "ok":
                del self.active_sessions[session_id]
                logger.info(f"Session '{session_id}' destroyed successfully")
                return True
            else:
                logger.error(f"Error destroying session: {data.get('message')}")
                return False

        except httpx.RequestError as e:
            logger.error(f"Failed to destroy session: {e}")
            return False

    async def __aenter__(self):
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit - cleanup all sessions."""
        for session_id in list(self.active_sessions.keys()):
            await self.destroy_session(session_id)


