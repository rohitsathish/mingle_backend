# %% Imports and Setup
import os
from dotenv import load_dotenv
from scrapegraphai.graphs import SmartScraperGraph
from pydantic import BaseModel
from typing import List, Optional

# Load environment variables
load_dotenv()
GEMINI_KEY = os.getenv("GEMINI_APIKEY")


# %% Define Schema
class Message(BaseModel):
    sender: str
    content: str
    timestamp: Optional[str] = None
    mentions: Optional[List[str]] = None


class ChatData(BaseModel):
    messages: List[Message]
    chat_name: Optional[str] = None


# %% Configure Graph
graph_config = {"llm": {"api_key": GEMINI_KEY, "model": "gemini-pro"}}

scraper = SmartScraperGraph(
    prompt="Extract message information including sender, content, and any mentions. Format timestamps if present.",
    config=graph_config,
    schema=ChatData,
)

# %% Test with sample data
sample_text = """
[2:45 PM] John: Hey @Alice, can you review the document?
[2:46 PM] Alice: Sure @John, I'll take a look now
"""

result = scraper.process(sample_text)
print(result)
