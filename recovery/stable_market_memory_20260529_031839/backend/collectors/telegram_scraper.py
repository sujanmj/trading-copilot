"""
TELEGRAM SCRAPER (User Client)
"""
import os
import sys

SESSION_STRING = os.environ.get('TELEGRAM_SESSION_STRING', '')
if not SESSION_STRING or len(SESSION_STRING) < 20:
    print("=" * 60)
    print("TELEGRAM ALPHA SCRAPER - Retail Sentiment Engine")
    print("=" * 60)
    print("[SKIP] Session not configured. Skipping gracefully.")
    print("=" * 60)
    sys.exit(0)

import json
import asyncio
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from dotenv import load_dotenv
from collections import Counter
from telethon.sync import TelegramClient
from telethon.sessions import StringSession

env_path = Path(__file__).resolve().parent.parent.parent / 'config' / 'keys.env'
load_dotenv(env_path, override=False)

API_ID = int(os.environ.get('TELEGRAM_API_ID', 0))
API_HASH = os.environ.get('TELEGRAM_API_HASH', '')

TARGET_CHANNELS = [
    'nifty50_options',
    'indianstockmarketnews',
    'banknifty_calls'
]

STOCK_PATTERN = r'\b[A-Z][A-Z0-9&-]{2,14}\b'
IGNORE_LIST = {'NIFTY', 'BANKNIFTY', 'FINNIFTY', 'CALL', 'PUT', 'CE', 'PE', 'SL', 'TGT', 'BUY', 'SELL'}
OUTPUT_FILE = Path(__file__).resolve().parent.parent.parent / 'data' / 'telegram_sentiment.json'

async def fetch_channel_history(client, channel_username, hours_back=4):
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours_back)
    messages = []
    try:
        entity = await client.get_entity(channel_username)
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
    client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
    await client.connect()
    if not await client.is_user_authorized():
        print("[ERROR] Session expired.")
        return
    all_messages = []
    for channel in TARGET_CHANNELS:
        print(f"[*] Scraping t.me/{channel}...")
        msgs = await fetch_channel_history(client, channel)
        all_messages.extend(msgs)
        print(f"  -> Found {len(msgs)} recent messages")
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
        'messages': all_messages[:30]
    }
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"[SUCCESS] Saved {len(all_messages)} messages")
    print("=" * 60)
    await client.disconnect()

def run_scraper():
    """Python 3.10+ safe entry — no deprecated get_event_loop()."""
    asyncio.run(main())


if __name__ == "__main__":
    try:
        run_scraper()
    except RuntimeError as e:
        # Thread/subprocess edge case — create dedicated loop once
        if 'event loop' in str(e).lower():
            loop = asyncio.new_event_loop()
            try:
                asyncio.set_event_loop(loop)
                loop.run_until_complete(main())
            finally:
                loop.close()
                asyncio.set_event_loop(None)
        else:
            raise