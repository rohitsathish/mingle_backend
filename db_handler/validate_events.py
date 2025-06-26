import json
import hashlib
from pathlib import Path
from typing import Dict, List, Optional


def validate_event(event: Dict) -> Optional[str]:
    """Validate a single event and return error message if invalid"""
    required_fields = {"name": str, "source_whatsapp_group": str, "post_datetime": str}

    for field, field_type in required_fields.items():
        if field not in event:
            return f"Missing required field: {field}"
        if not isinstance(event[field], field_type):
            return f"Invalid type for {field}: expected {field_type}, got {type(event[field])}"

    return None


def generate_event_id(event: Dict) -> str:
    """Generate a shorter event ID using MD5 instead of SHA-256"""
    source = "WhatsApp"
    id_string = f"{source}_{event['source_whatsapp_group']}_{event['post_datetime']}"
    return hashlib.md5(id_string.encode()).hexdigest()[
        :16
    ]  # Using first 16 chars of MD5


def validate_events_file(file_path: Path) -> List[Dict]:
    """Validate all events in a file and return list of validation errors"""
    with open(file_path) as f:
        data = json.load(f)

    validation_errors = []

    for idx, event in enumerate(data["events"]):
        error = validate_event(event)
        if error:
            validation_errors.append(
                {
                    "event_index": idx,
                    "event_name": event.get("name", "Unknown"),
                    "error": error,
                }
            )

    return validation_errors


def main():
    events_dir = Path(__file__).parent.parent / "parsed_events"
    all_errors = []

    for file_path in events_dir.glob("events_*.json"):
        errors = validate_events_file(file_path)
        if errors:
            all_errors.append({"file": file_path.name, "errors": errors})

    if all_errors:
        print("Validation errors found:")
        for file_errors in all_errors:
            print(f"\nFile: {file_errors['file']}")
            for error in file_errors["errors"]:
                print(f"  Event #{error['event_index']}: {error['event_name']}")
                print(f"    Error: {error['error']}")
        return False

    print("All events validated successfully!")
    return True


if __name__ == "__main__":
    main()
