import feedparser
import requests
import time
import json
import os

# --- Configuration ---
# List of RSS Feed URLs to monitor. You can add as many as you like.
RSS_FEEDS = [
    {"name": "Slashdot", "url": "https://rss.slashdot.org/Slashdot/slashdotMain"},
    {"name": "Phys.org", "url": "https://phys.org/rss-feed/"},
    {"name": "9to5 Linux", "url": "https://9to5linux.com/feed/atom"}, # This is the Atom feed
    # Add more feeds here following the same dictionary format
]

TELEGRAM_BOT_TOKEN = "YOUR_TELEGRAM_BOT_TOKEN"
TELEGRAM_CHAT_ID = "YOUR_TELEGRAM_CHAT_ID"
POLLING_INTERVAL_SECONDS = 300

LAST_ENTRIES_FILE = "last_entries.json"
last_entries = {}
feed_title_cache = {}


def load_last_entries():
    """Loads the last seen entry links from a file."""
    global last_entries
    if os.path.exists(LAST_ENTRIES_FILE):
        with open(LAST_ENTRIES_FILE, 'r') as f:
            try:
                last_entries = json.load(f)
                print(f"Loaded last entries from {LAST_ENTRIES_FILE}: {last_entries}")
            except json.JSONDecodeError:
                print(f"Warning: Could not decode {LAST_ENTRIES_FILE}. Starting fresh.")
                last_entries = {}
    else:
        print(f"No {LAST_ENTRIES_FILE} found. Starting fresh.")
    return last_entries

def save_last_entries():
    """Saves the current last seen entry links to a file."""
    with open(LAST_ENTRIES_FILE, 'w') as f:
        json.dump(last_entries, f, indent=4)
        print(f"Saved last entries to {LAST_ENTRIES_FILE}.")

def get_feed_and_latest_item(feed_url):
    """Fetches the entire feed and its latest item."""
    try:
        feed = feedparser.parse(feed_url)
        # Check for feed.bozo and feed.bozo_exception for parsing errors
        if hasattr(feed, 'bozo') and feed.bozo == 1:
            print(f"Warning: Bozo exception for {feed_url}: {feed.bozo_exception}")
            # Depending on severity, you might return None,None here
            # For now, we'll try to proceed even with a bozo exception if entries exist

        if feed.entries:
            return feed, feed.entries[0]
        return feed, None
    except Exception as e:
        print(f"Error fetching RSS feed {feed_url}: {e}")
        return None, None

def send_telegram_message(chat_id, text, bot_token, include_web_page_preview=True):
    """Sends a message to a Telegram chat."""
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": not include_web_page_preview
    }
    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()
        print("Telegram message sent successfully!")
        return True
    except requests.exceptions.RequestException as e:
        print(f"Error sending Telegram message: {e}")
        return False

def test_telegram_connection(chat_id, bot_token):
    """Sends a test message to Telegram to verify connection."""
    test_message = "<b>🚀 RSS Multi-Feed Bot Test Message 🚀</b>\n\n" \
                   "If you see this, your Telegram bot token and chat ID are correctly configured!"
    print("\nAttempting to send a test message to Telegram...")
    if send_telegram_message(chat_id, test_message, bot_token, include_web_page_preview=False):
        print("Test message sent successfully!")
        return True
    else:
        print("Failed to send test message. Please check your TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID.")
        return False

# MODIFIED: This function is now more robust in getting entry details
def format_feed_message(feed_name_from_config, feed_obj, entry):
    """Helper function to format the message for Telegram."""
    # Get feed title
    feed_title_display = getattr(feed_obj, 'title', feed_name_from_config)

    # Robustly get entry title
    entry_title = getattr(entry, 'title', 'No Title')

    # Robustly get entry link
    entry_url = getattr(entry, 'link', None)
    if entry_url is None and hasattr(entry, 'links') and entry.links:
        for link in entry.links:
            if link.get('rel') == 'alternate' and link.get('type') == 'text/html':
                entry_url = link.get('href')
                break
        if entry_url is None: # Fallback to first link if no specific HTML alternate
            entry_url = entry.links[0].get('href', 'No Link')
    if entry_url is None:
        entry_url = 'No Link'

    # Robustly get entry author
    entry_author = getattr(entry, 'author', 'N/A')
    if entry_author == 'N/A' and hasattr(entry, 'authors') and entry.authors:
        entry_author = entry.authors[0].get('name', 'N/A')

    # Robustly get entry content/summary
    entry_content = 'No Content Preview'
    if hasattr(entry, 'summary') and entry.summary:
        entry_content = entry.summary
    elif hasattr(entry, 'content') and entry.content:
        # For Atom feeds, content is often in entry.content[0].value
        entry_content = entry.content[0].get('value', 'No Content Preview')
    elif hasattr(entry, 'description') and entry.description: # Some RSS feeds use description
        entry_content = entry.description

    # Robustly get published/updated date
    entry_published = getattr(entry, 'published', None)
    if entry_published is None:
        entry_published = getattr(entry, 'updated', 'N/A') # Atom often uses 'updated'

    # Construct the message text
    message_text = (
        f"<b>📢 New from {feed_title_display}:</b>\n\n"
        f"<b>Title:</b> {entry_title}\n"
        f"<b>Author:</b> {entry_author}\n"
        f"<b>Published:</b> {entry_published}\n"
        f"<b>Link:</b> <a href='{entry_url}'>{entry_url}</a>\n"
        f"<b>Content Preview:</b> {entry_content[:200].replace('<', '&lt;').replace('>', '&gt;')}..." # Limit content preview & escape HTML
    )
    return message_text

def main():
    global last_entries
    global feed_title_cache

    print(f"Starting RSS Multi-Feed to Telegram automation. Polling every {POLLING_INTERVAL_SECONDS} seconds.")

    # --- Run Telegram connection test ---
    if not test_telegram_connection(TELEGRAM_CHAT_ID, TELEGRAM_BOT_TOKEN):
        print("Exiting due to Telegram connection test failure.")
        return

    # Load last entries from file at startup (for normal polling later)
    load_last_entries()

    # --- Initial startup confirmation: Send the very latest entry for EACH feed ---
    print("\n--- Sending startup confirmations for each feed ---")
    startup_summary_message = "✅ Bot started! Sending latest entry for each configured RSS feed:\n\n"
    send_telegram_message(
        TELEGRAM_CHAT_ID,
        startup_summary_message,
        TELEGRAM_BOT_TOKEN,
        include_web_page_preview=False
    )
    time.sleep(1)

    for feed_config in RSS_FEEDS:
        feed_name = feed_config['name']
        feed_url = feed_config['url']

        print(f"  Fetching latest entry for startup confirmation of '{feed_name}'...")
        feed_obj, latest_entry = get_feed_and_latest_item(feed_url)

        if feed_obj:
            feed_title_cache[feed_url] = getattr(feed_obj, 'title', feed_name)

        if latest_entry:
            confirmation_message = f"<b>[Startup Confirmation] Latest from {feed_name}:</b>\n\n" + \
                                   format_feed_message(feed_name, feed_obj, latest_entry)
            send_telegram_message(
                TELEGRAM_CHAT_ID,
                confirmation_message,
                TELEGRAM_BOT_TOKEN,
                include_web_page_preview=True
            )
            last_entries[feed_url] = latest_entry.link
        else:
            print(f"  Could not retrieve latest entry for '{feed_name}' for startup confirmation.")
            last_entries[feed_url] = None

        time.sleep(0.5)

    save_last_entries()

    # --- Main polling loop for new items ---
    while True:
        print(f"\n--- Checking feeds at {time.ctime()} ---")
        for feed_config in RSS_FEEDS:
            feed_name = feed_config['name']
            feed_url = feed_config['url']
            current_last_entry_link = last_entries.get(feed_url)

            print(f"Checking '{feed_name}' ({feed_url})...")
            feed_obj, latest_entry = get_feed_and_latest_item(feed_url)

            if feed_obj and feed_url not in feed_title_cache:
                 feed_title_cache[feed_url] = getattr(feed_obj, 'title', feed_name)

            if latest_entry:
                if current_last_entry_link is None or latest_entry.link != current_last_entry_link:
                    print(f"  New item found for '{feed_name}': {latest_entry.title}")

                    message_text = format_feed_message(feed_name, feed_obj, latest_entry)

                    send_telegram_message(
                        TELEGRAM_CHAT_ID,
                        message_text,
                        TELEGRAM_BOT_TOKEN,
                        include_web_page_preview=True
                    )

                    last_entries[feed_url] = latest_entry.link
                    save_last_entries()
                else:
                    print(f"  No new items for '{feed_name}'.")
            else:
                print(f"  Could not retrieve any items for '{feed_name}'.")

        print(f"--- Finished checking all feeds. Sleeping for {POLLING_INTERVAL_SECONDS} seconds. ---")
        time.sleep(POLLING_INTERVAL_SECONDS)

if __name__ == "__main__":
    main()
