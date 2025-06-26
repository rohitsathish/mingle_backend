"""Simplified OpenRouter completion implementation with caching."""

from typing import Any, Dict, List, Optional
import hashlib
import json

import httpx
import nest_asyncio

nest_asyncio.apply()

# Simple in-memory cache
COMPLETION_CACHE = {}


def _generate_cache_key(model: str, messages: List[Dict[str, Any]], **kwargs) -> str:
    """Generate a cache key from request parameters."""
    # Create a hashable representation of the request
    cache_data = {
        "model": model,
        "messages": messages,
        **{k: v for k, v in kwargs.items() if v is not None}
    }
    # Convert to a stable string representation and hash it
    data_str = json.dumps(cache_data, sort_keys=True)
    return hashlib.md5(data_str.encode()).hexdigest()


async def openrouter_completion(
    model: str,
    messages: List[Dict[str, Any]],
    api_key: str,
    response_format: Optional[Dict] = None,
    tools: Optional[List[Dict]] = None,
    tool_choice: Optional[str] = None,
) -> Dict:
    """Simplified OpenRouter API handler with caching."""
    OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
    
    # Generate cache key
    cache_key = _generate_cache_key(
        model, messages, response_format=response_format, 
        tools=tools, tool_choice=tool_choice
    )
    
    # Check cache first
    if cache_key in COMPLETION_CACHE:
        return COMPLETION_CACHE[cache_key]

    # Build request payload
    payload = {
        "model": model,
        "messages": messages,
    }

    # Add optional parameters
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = tool_choice if tool_choice else "auto"

    if response_format:
        if response_format.get("type") == "json_object":
            payload["response_format"] = {
                "type": "json_schema",
                "schema": response_format.get("response_schema", {}),
            }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://mingle.backend",  # Replace with actual URL in production
        "X-Title": "Mingle Backend",
    }

    # Configure timeout
    timeout = httpx.Timeout(30.0)  # 30 seconds timeout

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                OPENROUTER_URL, headers=headers, json=payload
            )
            
            if response.status_code != 200:
                raise Exception(
                    f"OpenRouter API call failed with status {response.status_code}: {response.text}"
                )

            response_data = response.json()
            
            # Cache successful response
            COMPLETION_CACHE[cache_key] = response_data
            return response_data
    except Exception as e:
        raise Exception(f"OpenRouter API call failed: {str(e)}")


# Example usage
import asyncio

if __name__ == "__main__":
    asyncio.run(
        openrouter_completion(
            model="google/gemini-2.0-flash-exp:free",
            messages=[{"role": "user", "content": "Hello!"}],
            api_key="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",
            response_format={
                "type": "json_object",
                "response_schema": {
                    "type": "object",
                    "properties": {
                        "answer": {
                            "type": "string",