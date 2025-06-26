"""Utility functions for image handling."""

import json
import logging
import os
from typing import List, Optional

# Setup logging
logger = logging.getLogger(__name__)


def load_base64_images_from_json(json_path: str, max_images: int = 4) -> List[str]:
    """
    Extract base64-encoded image URLs from a messages JSON file.

    Args:
        json_path: Path to the JSON file with messages containing base64 images
        max_images: Maximum number of images to extract

    Returns:
        List of base64 image URLs or empty list if none found
    """
    try:
        # Check if file exists
        if not os.path.exists(json_path):
            logger.error(f"JSON file not found: {json_path}")
            return []

        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Extract base64 image URLs
        base64_images = []

        # Navigate through the JSON structure
        if "whatsapp_groups" in data:
            for group in data["whatsapp_groups"]:
                if "messages" in group:
                    for message_id, messages in group["messages"].items():
                        for message in messages:
                            if "imgs" in message and isinstance(message["imgs"], dict):
                                # Extract the first image from each message
                                for img_id, img_data in message["imgs"].items():
                                    if img_data.startswith("data:image"):
                                        base64_images.append(img_data)
                                        if len(base64_images) >= max_images:
                                            return base64_images

        logger.info(f"Extracted {len(base64_images)} base64 images from {json_path}")
        return base64_images

    except json.JSONDecodeError:
        logger.error(f"Invalid JSON in file: {json_path}")
        return []
    except Exception as e:
        logger.error(f"Error extracting base64 images: {str(e)}")
        return []


# Sample test images fallback if no base64 images are found
FALLBACK_IMAGE_URLS = [
    "https://cdn.venngage.com/template/thumbnail/small/37de5deb-1ca7-4e60-b254-374b08708817.webp",
    "https://static.vecteezy.com/system/resources/previews/000/542/362/non_2x/vector-summer-event-poster.jpg",
    "https://i.pinimg.com/564x/cc/f7/27/ccf7273988e9a11a1c4cfbee544c9593.jpg",
    "https://images.unsplash.com/photo-1742943892627-f7e4ddf91224?q=80&w=1738&auto=format&fit=crop&ixlib=rb-4.0.3&ixid=M3wxMjA3fDB8MHxwaG90by1wYWdlfHx8fGVufDB8fHx8fA%3D%3D",
]


def get_test_image_urls(
    json_path: Optional[str] = None, max_images: int = 4
) -> List[str]:
    """
    Get a list of image URLs for testing purposes.

    Attempts to load base64 images from the provided JSON file.
    Falls back to hardcoded URLs if no JSON file is provided or no images found.

    Args:
        json_path: Optional path to JSON file with base64 images
        max_images: Maximum number of images to return

    Returns:
        List of image URLs (base64 or web URLs)
    """
    if json_path:
        base64_images = load_base64_images_from_json(json_path, max_images)
        if base64_images:
            return base64_images

    # Fallback to hardcoded URLs
    logger.info("Using fallback image URLs")
    return FALLBACK_IMAGE_URLS[:max_images]
