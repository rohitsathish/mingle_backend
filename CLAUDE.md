# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a WhatsApp Web scraper called "Mingle Scraper" that captures event-relevant data from specified groups. The system scrapes WhatsApp groups for events happening in Bengaluru, processes the messages through LLM-based parsing to extract structured event information, and stores the data.

## Common Development Commands

### Setup Commands
```bash
# Install Python dependencies
pip install -r requirements.txt

# Install Playwright browsers
playwright install chromium
```

### Running the Application
```bash
# Run the main scraper
python main.py

# Test database operations
python db_handler/test.py

# Run LLM parsing on scraped messages
python llm_parsing/llm_parse.py
```

### Testing and Validation
```bash
# Validate parsed events for duplicates
python db_handler/test.py
```

## Architecture Overview

### Core Components

1. **Scraper Module** (`scraper.py`, `main.py`):
   - Uses Playwright to automate WhatsApp Web
   - Scrapes messages from archived groups based on configurable patterns
   - Handles persistent Chrome sessions with debugging port (9222)
   - Extracts both text messages and images from WhatsApp chats

2. **Configuration** (`config.py`):
   - Defines target WhatsApp groups with "chatter" flags
   - Contains event detection patterns and selectors
   - Manages file paths and time thresholds
   - Category mapping for event classification

3. **Message Processing** (`messages_handler.py`):
   - Handles JSON file creation and management
   - Cleans and normalizes message text
   - Manages incremental scraping based on timestamps

4. **LLM Parsing** (`llm_parsing/`):
   - Uses various LLM providers (OpenAI, Google, Anthropic) via OpenRouter
   - Converts raw WhatsApp messages into structured event data
   - Handles image analysis for event posters/flyers
   - Outputs structured JSON with event details

5. **Database Handler** (`db_handler/`):
   - Validates event data structure
   - Checks for duplicate events
   - Manages event uploads and schema validation

### Data Flow

1. WhatsApp groups are scraped for messages → `messages/messages_YYYYMMDD_HHMM.json`
2. Messages are parsed by LLMs → `llm_parsing/outputs/events_YYYY-MM-DD_HH-MM_modelname.json`
3. Events are validated and uploaded to database
4. Parsed events stored in → `parsed_events/events_YYYYMMDD.json`

### Key Configuration

- **Groups**: Defined in `config.py` with chatter flags (announcement vs discussion groups)
- **Event Patterns**: Regex patterns for detecting event-related messages
- **Time Thresholds**: Controls when to create new files vs append to existing ones
- **Chrome Profile**: Persistent browser session stored in `chrome_profile/`

### Important File Patterns

- Messages: `messages/messages_YYYYMMDD_HHMM.json`
- LLM Outputs: `llm_parsing/outputs/events_YYYY-MM-DD_HH-MM_modelname.json`
- Parsed Events: `parsed_events/events_YYYYMMDD.json`

## Development Notes

- The scraper maintains persistent Chrome sessions to avoid repeated WhatsApp Web logins
- Image extraction from WhatsApp uses blob URLs that must be processed while the page is active
- LLM parsing supports multiple providers and models via OpenRouter API
- Event detection uses both keyword patterns and LLM analysis
- The system handles both "chatty" groups (require filtering) and announcement-only groups