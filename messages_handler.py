import json
import os
import re
import unicodedata
from datetime import datetime, timezone
from typing import Dict, Optional, List, Any
from zoneinfo import ZoneInfo
import glob
from unidecode import unidecode

from config import NEW_FILE_THRESHOLD, GROUP_SCRAPE_THRESHOLD, MESSAGES_DIR, MESSAGES_JSON_PATH


class MessagesHandler:
    """Handler for WhatsApp messages JSON operations."""

    def __init__(self):
        self.base_dir = MESSAGES_DIR
        os.makedirs(self.base_dir, exist_ok=True)

    def _get_latest_messages_file(self) -> Optional[str]:
        pattern = os.path.join(self.base_dir, "messages_*.json")
        files = glob.glob(pattern)
        if not files:
            return None
        return max(files, key=os.path.getctime)

    def _clean_message_text(self, text: str) -> str:
        """Clean message text while preserving single newlines."""
        if not text:
            return ""

        # Convert to ASCII-compatible form
        text = unidecode(text)

        # Remove certain invisible or special chars
        text = text.replace("\u200b", "")
        text = text.replace("\xa0", " ")
        text = text.replace("\t", " ")

        # Normalize form
        text = unicodedata.normalize("NFKC", text)

        # Standardize line breaks
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        # Convert multiple newlines -> single newline
        text = re.sub(r"\n+", "\n", text)

        # Optionally strip leading/trailing newlines
        text = text.strip("\n")

        # Remove undesired control chars except newline
        cleaned_chars = []
        for ch in text:
            if unicodedata.category(ch)[0] != "C" or ch == "\n":
                cleaned_chars.append(ch)

        return "".join(cleaned_chars)

    def _clean_dict(self, obj: Any) -> Any:
        if isinstance(obj, dict):
            return {k: self._clean_dict(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._clean_dict(item) for item in obj]
        elif isinstance(obj, str):
            return self._clean_message_text(obj)
        return obj

    def create_messages_file(self, groups_data: List[Dict]) -> None:
        """Create messages JSON file with cleaned data."""
        try:
            output_data = {
                "created_at": datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%Y-%m-%dT%H:%M%z"),
                "whatsapp_groups": groups_data,
            }
            cleaned_data = self._clean_dict(output_data)

            if not os.path.exists(MESSAGES_DIR):
                os.makedirs(MESSAGES_DIR, exist_ok=True)

            # We do NOT override iterencode to replace '\\n'.
            # Standard JSON will store them as \n (escaped newlines).
            with open(MESSAGES_JSON_PATH, "w", encoding="utf-8") as f:
                json.dump(cleaned_data, f, indent=2, ensure_ascii=False)

        except Exception as e:
            print(f"Error creating messages file: {e}")
            raise

    def get_last_scrape_datetime(self) -> Optional[datetime]:
        """Get the created_at datetime from the latest messages file."""
        latest_file = self._get_latest_messages_file()
        if not latest_file:
            return None

        try:
            with open(latest_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                created_at = data.get("created_at")
                if created_at:
                    return datetime.fromisoformat(created_at)
        except Exception as e:
            print(f"Error reading messages file: {e}")
        return None

