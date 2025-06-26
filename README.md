# Mingle Scraper

A WhatsApp Web scraper to capture event-relevant data from specified groups.

## Setup

1. Install Python dependencies:
```bash
pip install -r requirements.txt
```

2. Install Playwright browsers:
```bash
playwright install chromium
```

## Usage

Run the scraper:
```bash
python main.py
```

The script will:
1. Open WhatsApp Web in a browser window
2. Prompt for QR code scan if needed
3. Scrape messages from configured groups
4. Save results to `messages.json`

## Configuration

Edit `config.py` to:
- Modify group list and chatter flags
- Adjust days to look back for messages
- Change output file path