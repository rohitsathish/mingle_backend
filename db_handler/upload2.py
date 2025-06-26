#!/usr/bin/env python3
"""
Event uploader for WhatsApp events to Supabase.

This script reads JSON events from parsed_events, transforms them
to match the PostgreSQL schema, and does a single batch upsert via PostgREST.
"""

import os
import sys
import json
import hashlib
import asyncio
from datetime import datetime
from typing import Any, Dict, List, Optional
import re
import aiohttp
from dotenv import load_dotenv
from config import GROUP_CONTACT_DETAILS

# python -m db_handler.upload2 events_0625_1635_gemini-2.5-flas_messages_20250623_1541.json

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

    def validate_required_fields(self, event: Dict[str, Any]) -> Optional[str]:
        """Check presence and basic type of mandatory fields for minimal viability."""
        required = {"name": str, "source_whatsapp_group": str, "post_datetime": str}
        for field, ftype in required.items():
            if field not in event:
                return f"Missing required field: {field}"
            if not isinstance(event[field], ftype):
                return f"Invalid type for {field}: expected {ftype.__name__}"
        return None

    def validate_data_types(self, e: Dict[str, Any]) -> Optional[str]:
        """Validate each field to ensure it matches the DB's schema expectations."""
        # Arrays
        array_fields = ["categories", "tags"]
        for field in array_fields:
            val = e.get(field)
            if val is not None:
                if not isinstance(val, list):
                    return f"'{field}' must be a list"
                if any(not isinstance(item, str) for item in val):
                    return f"All items in '{field}' must be strings"

        # Numeric: cost
        if "cost" in e and e["cost"] is not None:
            try:
                float(e["cost"])  # just test convert
            except (ValueError, TypeError):
                return "'cost' must be numeric"

        # Booleans
        bool_fields = ["is_update", "is_cancelled"]
        for bf in bool_fields:
            if bf in e and e[bf] not in [True, False, None]:
                return f"'{bf}' must be boolean"

        # Datetime
        datetime_fields = ["post_datetime", "start_datetime", "end_datetime"]
        for dt in datetime_fields:
            val = e.get(dt)
            if val:
                try:
                    datetime.fromisoformat(val.replace("Z", "+00:00"))
                except ValueError:
                    return f"'{dt}' must be a valid ISO datetime"

        # links must be JSON-serializable
        if "links" in e and e["links"] is not None:
            try:
                json.dumps(e["links"])
            except (TypeError, ValueError):
                return "'links' must be JSON-serializable"

        return None

    async def fetch_place_details(self, address: str) -> Optional[Dict[str, Any]]:
        """Use Google Place TextSearch for the address to get place_id, lat/lng, and formatted_address."""
        if not address or not self.session:
            return None

        url = "https://maps.googleapis.com/maps/api/place/textsearch/json"
        params = {
            "query": address,
            "key": self.gmaps_apikey,
            "fields": "place_id,geometry/location,formatted_address",  # Specify required fields here
        }
        try:
            async with self.session.get(url, params=params, timeout=10) as resp:
                data = await resp.json()
                if data.get("status") != "OK" or not data.get("results"):
                    print(f"TextSearch returned {data.get('status')} for '{address}'")
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
        except Exception as ex:
            print(f"Error in fetch_place_details for '{address}': {ex}")
            return None

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

    async def transform_event(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        """Transform a raw event into a fully qualified DB row dict."""
        # 1. Check required fields
        # missing_err = self.validate_required_fields(raw)
        # if missing_err:
        #     raise ValueError(missing_err)

        # 2. Type check
        # type_err = self.validate_data_types(raw)
        # if type_err:
        #     raise ValueError(type_err)

        # 3. Generate event_id
        ev_id = self.generate_event_id(raw)

        # 4. Default booleans
        is_update = raw.get("is_update", False)
        is_cancelled = raw.get("is_cancelled", False)

        # 5. cost
        cost_val = raw.get("cost")
        if cost_val is not None:
            try:
                cost_val = float(cost_val)
            except (ValueError, TypeError):
                cost_val = None

        # 6. Attempt geocoding
        llm_address = raw.get("venue_address_llm")
        venue_name = raw.get("venue_name")
        area = raw.get("area")
        event_type = raw.get("event_type")
        place_info = None
        contact_string = None

        if event_type != "online":
            if llm_address:
                place_info = await self.fetch_place_details(llm_address)
            elif venue_name and area:
                if area.lower() in llm_address.lower():
                    place_info = await self.fetch_place_details(f"{venue_name}")
                else:
                    place_info = await self.fetch_place_details(f"{venue_name}, {area}")
            elif raw.get("source_whatsapp_group") in GROUP_CONTACT_DETAILS:
                contact_details = GROUP_CONTACT_DETAILS.get(raw.get("source_whatsapp_group"), {})
                contact_info = " or ".join([f"{k}: {v}" for k, v in contact_details.items()])
                contact_string = f"Venue details for this event need to be obtained by contacting the organizer at {contact_info}"
            else:
                raise ValueError(
                    f"Missing llm address, venue_name and area for geocoding and contact details. Cannot proceed for event {raw.get('name', 'unknown')}."
                )

        gmaps_link = raw.get("gmaps_link")
        lat_long = None
        gmaps_address = None

        if place_info:
            lat_long = f"SRID=4326;POINT({place_info['lng']} {place_info['lat']})"
            gmaps_address = place_info.get("formatted_address")
            if not gmaps_link:
                gmaps_link = f"https://www.google.com/maps/place/?q=place_id:{place_info['place_id']}"

        # Create structured event record based on the database schema
        return {
            "event_id": ev_id,
            "short_name": raw.get("short_name"),
            "name": raw["name"],
            "event_type": raw.get("event_type"),
            "categories": raw.get("categories", []),
            "tags": raw.get("tags", []),
            "summary": raw.get("summary"),
            "organizer": raw.get("organizer"),
            "cost": cost_val,
            "source_created_at": raw.get("source_created_at"),
            "source_json_name": raw.get("source_json_name"),
            "source_whatsapp_group": raw["source_whatsapp_group"],
            "venue_name": raw.get("venue_name"),
            "venue_address_llm": llm_address,
            "contact_string": contact_string,
            "area": raw.get("area"),
            "post_datetime": raw.get("post_datetime"),
            "start_date": raw.get("start_date"),
            "start_time": raw.get("start_time"),
            "end_date": raw.get("end_date"),
            "end_time": raw.get("end_time"),
            "is_update": is_update,
            "is_cancelled": is_cancelled,
            "info_link": raw.get("info_link"),
            "reg_link": raw.get("reg_link"),
            "gmaps_link": gmaps_link,
            "notes_to_admin": raw.get("notes_to_admin"),
            # Processed columns
            "source": "WhatsApp",
            "lat_long": lat_long,
            "venue_address_gmaps": gmaps_address,
            # created_at is handled by DB default
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
            # "on_conflict=event_id" might be needed in your Supabase config or
            # you can rely on primary key conflict. Usually "resolution=merge-duplicates" or "upsert".
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

    def validate_events(self, events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Checks only the presence of minimal required fields for each event."""
        errors = []
        for idx, e in enumerate(events):
            res = self.validate_required_fields(e)
            if res:
                errors.append({"index": idx, "name": e.get("name"), "error": res})
        return errors


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
