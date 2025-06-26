#!/usr/bin/env python3
"""
Event uploader for WhatsApp events to Supabase.

This script reads JSON events from the messages directory, transforms them
to match the PostgreSQL schema, and does a single batch upsert via PostgREST.
"""

import asyncio
import json
import os
import re
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional

import aiohttp
from dotenv import load_dotenv

load_dotenv()  # Load environment variables from .env


class EventUploader:
    """Handles event transformation and bulk upload to Supabase via PostgREST."""

    def __init__(self) -> None:
        self.db_url = os.getenv("DB_URL")  # e.g. https://<project>.supabase.co
        self.anon_key = os.getenv("ANON_KEY")  # supabase anon or service role key
        self.gmaps_apikey = os.getenv("GMAPS_APIKEY")

        # Quick check for required env variables
        if not self.db_url or not self.anon_key or not self.gmaps_apikey:
            raise ValueError(
                "Missing DB_URL, ANON_KEY, or GMAPS_APIKEY environment variables."
            )

        self.session: Optional[aiohttp.ClientSession] = None

    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()

    @staticmethod
    def read_json_file(file_path: str) -> Dict[str, Any]:
        """Reads JSON from the specified file path and returns it as a dict."""
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)

    @staticmethod
    def generate_event_id(evt: Dict[str, Any]) -> str:
        """Generate stable event_id from short_name and start date/time."""
        # Extract alphanumeric characters from short_name
        short_name = re.sub(r"[^a-zA-Z0-9\s]", "", evt.get("short_name", ""))

        # Take first 3 space-delimited terms
        terms = short_name.split()[:3]
        try:
            name_part = "-".join(terms)
        except Exception as e:
            raise ValueError(f"Error processing short_name '{short_name}': {e}")

        # Format date/time part
        date_str = evt.get("start_date", "")
        time_str = evt.get("start_time", "")

        datetime_part = ""
        try:
            date = datetime.strptime(date_str, "%Y-%m-%d")
            datetime_part = date.strftime("%d%m%y")

            if time_str:
                # Handle timezone info in time string
                time_part = time_str.split("+")[0]
                time = datetime.strptime(time_part, "%H:%M")
                datetime_part += f"-{time.strftime('%H%M')}"
        except ValueError:
            raise ValueError(f"Invalid date or time format: {date_str}, {time_str}")

        return f"{name_part}-{datetime_part}"

    async def fetch_place_details(
        self, venue_name: Optional[str], address: Optional[str]
    ) -> Optional[Dict[str, Any]]:
        """Use Google Place TextSearch with venue name and address to get place details."""
        if not self.session or (not venue_name and not address):
            return None

        # Combine venue name and address for better search results
        if venue_name in address:
            search_query = address
        else:
            search_query = ", ".join(filter(None, [venue_name, address]))

        url = "https://maps.googleapis.com/maps/api/place/textsearch/json"
        params = {
            "query": search_query,
            "key": self.gmaps_apikey,
            "fields": "place_id,geometry/location,formatted_address",
        }

        async with self.session.get(url, params=params, timeout=10) as resp:
            data = await resp.json()
            if data.get("status") != "OK" or not data.get("results"):
                print(f"TextSearch returned {data.get('status')} for '{search_query}'")
                print(f"Full response: {json.dumps(data, indent=2)}")
                return None

            top_result = data["results"][0]
            place_id = top_result["place_id"]
            lat = top_result["geometry"]["location"]["lat"]
            lng = top_result["geometry"]["location"]["lng"]
            formatted_addr = top_result.get("formatted_address")

            return {
                "place_id": place_id,
                "lat": lat,
                "lng": lng,
                "formatted_address": formatted_addr,
            }

    async def transform_event(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        """Transform a raw event into a fully qualified DB row dict."""
        # 1. Generate event_id
        ev_id = self.generate_event_id(raw)

        # 2. Handle cost
        cost_val = raw.get("cost")
        if cost_val is not None:
            try:
                cost_val = float(cost_val)
            except (ValueError, TypeError):
                cost_val = None

        # 3. Check if gmaps_link exists in the links
        links_data = raw.get("links", {})
        gmaps_link = (
            links_data.get("gmaps_link") if isinstance(links_data, dict) else None
        )

        # 4. If no gmaps_link, attempt geocoding
        lat_long = None
        gmaps_address = None

        # Always attempt to fetch place details
        venue_name = raw.get("venue_name")
        llm_address = raw.get("venue_address_llm")

        lat_long = None
        gmaps_address = None

        if venue_name or llm_address:
            place_info = await self.fetch_place_details(venue_name, llm_address)

            if place_info:
                lat_long = f"SRID=4326;POINT({place_info['lng']} {place_info['lat']})"
                gmaps_address = place_info.get("formatted_address")

            # Only use the generated gmaps_link if one doesn't already exist
            if not gmaps_link:
                gmaps_link = f"https://www.google.com/maps/place/?q=place_id:{place_info['place_id']}"

        # 5. Create the transformed event
        return {
            "event_id": ev_id,
            "short_name": raw.get("short_name"),
            "name": raw.get("name"),
            "categories": raw.get("categories", []),
            "tags": raw.get("tags", []),
            "summary": raw.get("summary"),
            "notes_to_admin": raw.get("notes_to_admin"),
            "cost": cost_val,
            "source_whatsapp_group": raw.get("source_whatsapp_group"),
            "source_json_name": raw.get("source_json_name"),
            "source": "WhatsApp",
            "organizer": raw.get("organizer"),
            "venue_name": raw.get("venue_name"),
            "area": raw.get("area"),
            "venue_address_llm": raw.get("venue_address_llm"),
            "venue_address_gmaps": gmaps_address,
            "post_datetime": raw.get("post_datetime"),
            "start_date": raw.get("start_date"),
            "start_time": raw.get("start_time"),
            "end_date": raw.get("end_date"),
            "end_time": raw.get("end_time"),
            "is_update": raw.get("is_update", False),
            "is_cancelled": raw.get("is_cancelled", False),
            "links": links_data,
            "lat_long": lat_long,
            "gmaps_link": gmaps_link,
        }

    async def upload_events(self, events: List[Dict[str, Any]]) -> None:
        """Transforms each event, then batch POST to the 'events' table with upsert-like logic."""
        if not self.session:
            raise RuntimeError("No HTTP session available. Must be in async context.")

        # Transform all events
        final_list: List[Dict[str, Any]] = []
        for item in events:
            row = await self.transform_event(item)
            final_list.append(row)

        # Prepare request
        headers = {
            "Authorization": f"Bearer {self.anon_key}",
            "apikey": self.anon_key,
            "Content-Type": "application/json",
            "Prefer": "resolution=merge-duplicates",
        }

        url = f"{self.db_url}/rest/v1/events"

        try:
            async with self.session.post(
                url, headers=headers, json=final_list, timeout=30
            ) as resp:
                if resp.status not in (200, 201):
                    error_text = await resp.text()
                    raise ValueError(
                        f"Batch upload failed (status {resp.status}): {error_text}"
                    )
                print(f"Successfully uploaded {len(final_list)} events.")
        except Exception as ex:
            raise RuntimeError(f"Error during batch upload: {ex}")


async def main_async():
    """Async main entrypoint."""
    if len(sys.argv) < 2:
        print(
            "Usage: python upload.py <events_json_filename> [events_json_filename2 ...]"
        )
        sys.exit(1)

    file_args = sys.argv[1:]
    script_dir = os.path.dirname(os.path.abspath(__file__))
    messages_dir = os.path.join(os.path.dirname(script_dir), "messages")

    async with EventUploader() as uploader:
        for filename in file_args:
            path = os.path.join(messages_dir, filename)
            if not os.path.exists(path):
                print(f"File not found: {path}")
                continue

            data = uploader.read_json_file(path)
            if "events" not in data:
                print(f"No 'events' key in {path}")
                continue

            ev_list = data["events"]
            print(f"\nProcessing {len(ev_list)} events from {path} ...")
            try:
                await uploader.upload_events(ev_list)
            except Exception as exc:
                print(f"Error uploading events from {path}: {exc}")
                sys.exit(1)


def main():
    """Sync wrapper for the async main function."""
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
