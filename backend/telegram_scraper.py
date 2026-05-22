"""
TELEGRAM SCRAPER (User Client)
Reads the "Retail Whisper" and Options setups from top Telegram channels.
Uses StringSession to run headless on Railway.
"""

import os
import json
import asyncio
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from dotenv import load_dotenv
from collections import Counter

from telethon.sync import TelegramClient
from telethon.sessions import StringSession

# Load env vars
env_path = Path(__file__).parent.parent / 'config' / 'keys.env'
load_dotenv(env_path, override=False)

API_ID = int(os.environ.get('TELEGRAM_API_ID', 0))
API_HASH = os.environ.get('TELEGRAM_API_HASH', '')
SESSION_STRING = os.environ.get('TELEGRAM_SESSION_STRING', '')

# Replace these with popular public Indian trading channels you want to track
TARGET_CHANNELS = [
    'nifty50_options', 
    'indianstockmarketnews',
    'banknifty_calls'
]

# Basic NSE Ticker Extraction
STOCK_PATTERN = r'\b[A-Z][A-Z0-9&-]{2,14}\b'
IGNORE_LIST = {'NIFTY', 'BANKNIFTY', 'FINNIFTY', 'CALL', 'PUT', 'CE', 'PE', 'SL', 'TGT', 'BUY', 'SELL'}

OUTPUT_FILE = Path(__file__).parent.parent / 'data' / 'telegram_sentiment.json'

async def fetch_channel_history(client, channel_username, hours_back=4):
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours_back)
    messages = []
    
    try:
        # Get the entity (channel)
        entity = await client.get_entity(channel_username)
        
        # Iterate through messages
        async for msg in client.iter_messages(entity, limit=50):
            if msg.date < cutoff:
                break
                
            if msg.text:
                messages.append({
                    'channel': channel_username,
                    'text': msg.text,
                    'views': msg.views or 0,
                    'date': msg.date.isoformat()
                })
        return messages
    except Exception as e:
        print(f"  [ERROR] Could not scrape {channel_username}: {e}")
        return []

async def main():
    print("=" * 60)
    print("TELEGRAM ALPHA SCRAPER - Retail Sentiment Engine")
    print("=" * 60)
    
    if not SESSION_STRING:
        print("[ERROR] TELEGRAM_SESSION_STRING is missing. Run local setup script first.")
        return

    client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
    
    await client.connect()
    if not await client.is_user_authorized():
        print("[ERROR] Session String is invalid or expired. Generate a new one.")
        return

    all_messages = []
    for channel in TARGET_CHANNELS:
        print(f"[*] Scraping t.me/{channel}...")
        msgs = await fetch_channel_history(client, channel)
        all_messages.extend(msgs)
        print(f"  -> Found {len(msgs)} recent messages")

    # Analyze Data
    ticker_mentions = Counter()
    for msg in all_messages:
        words = re.findall(STOCK_PATTERN, msg['text'])
        for w in words:
            if w not in IGNORE_LIST:
                ticker_mentions[w] += 1

    top_tickers = dict(ticker_mentions.most_common(15))
    
    output = {
        'last_updated': datetime.now(timezone.utc).isoformat(),
        'total_messages_scanned': len(all_messages),
        'top_mentioned_stocks': top_tickers,
        'messages': all_messages[:30] # Save top 30 for AI context
    }
    
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
        
    print("-" * 60)
    print(f"[SUCCESS] Saved {len(all_messages)} alpha messages. Top ticker: {list(top_tickers.keys())[0] if top_tickers else 'None'}")
    print("=" * 60)
    
    await client.disconnect()

def run_scraper():
    # Because telethon is async, we wrap it
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())

if __name__ == "__main__":
    run_scraper()