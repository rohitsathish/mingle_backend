import argparse
from scraper import WhatsAppScraper
from config import GROUPS


def main():
    """Main entry point for the WhatsApp scraper."""
    keep_open = True
    test_run = False
    days_back = 10

    print("Starting Mingle Scraper...")
    print(f"Test run: {'enabled' if test_run else 'disabled'}")
    print(f"Looking back {days_back} days for messages")

    # Create scraper instance with command line arguments
    scraper = WhatsAppScraper(keep_open=keep_open, test_run=test_run)
    scraper.start_playwright()

    try:
        if scraper.initialize():
            if scraper.is_port_in_use():
                print("Using existing Chrome session...")
            else:
                print("Starting new Chrome session...")

            if scraper.wait_for_login():
                print("WhatsApp Web login successful!")
                # Process groups with days_back parameter
                found_groups = scraper.find_groups(list(GROUPS.keys()), days_back)
                if found_groups:
                    print(f"Successfully processed groups: {found_groups}")
                else:
                    print("No groups were processed")
            else:
                print("Login failed")
        else:
            print("Failed to initialize WhatsApp Web")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        scraper.stop_playwright()
        print("Script completed")


if __name__ == "__main__":
    main()
