# %%
import json
from pathlib import Path
import hashlib
from collections import defaultdict
from typing import Dict, List, Tuple

#%%

#from config import GROUP_CONTACT_DETAILS
from pathlib import Path

os.chdir(Path.cwd().parent)
from config import GROUP_CONTACT_DETAILS

contact_details = GROUP_CONTACT_DETAILS.get("BLR Events Hub")
contact_info = " or ".join([f"{k}: {v}" for k, v in contact_details.items()])
contact_info
# %%
def check_event_id_duplicates(date_str: str) -> Tuple[bool, Dict[str, List[dict]]]:
    """
    Check for duplicate event_ids in a parsed events file.

    Args:
        date_str: Date string in format YYYYMMDD

    Returns:
        Tuple of (has_duplicates, duplicate_dict)
        where duplicate_dict maps event_ids to list of events with that id
    """
    script_path = Path(__file__).resolve()
    parsed_dir = script_path.parent.parent / "parsed_events"
    events_file = parsed_dir / f"events_{date_str}.json"

    with events_file.open("r", encoding="utf-8") as f:
        data = json.load(f)
        events = data.get("events", [])

    # Track events by their generated id
    events_by_id = defaultdict(list)

    for event in events:
        # Generate event_id using same logic as uploader
        source = "WhatsApp"
        source_group = event.get("source_whatsapp_group", "")
        post_datetime = event.get("post_datetime", "")
        id_string = f"{source}_{source_group}_{post_datetime}"
        event_id = hashlib.md5(id_string.encode()).hexdigest()[:16]

        events_by_id[event_id].append(event)

    # Filter to only duplicates
    duplicates = {k: v for k, v in events_by_id.items() if len(v) > 1}

    return bool(duplicates), duplicates


# %%
# Example usage
date_str = "20250127"
has_dupes, dupes = check_event_id_duplicates(date_str)
print(f"Has duplicates: {has_dupes}")
if has_dupes:
    for event_id, events in dupes.items():
        print(f"\nDuplicate ID: {event_id}")
        for i, event in enumerate(events, 1):
            print(f"Event {i}:")
            print(f"  Name: {event.get('name')}")
            print(f"  Source Group: {event.get('source_whatsapp_group')}")
            print(f"  Post DateTime: {event.get('post_datetime')}")
