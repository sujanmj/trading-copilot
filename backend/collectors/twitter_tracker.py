"""
X/TWITTER TRACKER (Nitter RSS Method)
Bypasses Twitter API paywalls to get instant FinTwit updates.
Tracks RBI, NSE, and breaking market news accounts.
"""

import json
import feedparser
import requests
from datetime import datetime, timezone, timedelta
from pathlib import Path
import re

# Nitter instances change occasionally. These are reliable public ones.
NITTER_INSTANCES = [
    "https://nitter.net",
    "https://nitter.cz",
    "https://nitter.privacydev.net",
    "https://nitter.poast.org"
]

# Top tier Indian Financial Twitter accounts
TWITTER_ACCOUNTS = [
    "RBI",              # Central Bank
    "NSEIndia",         # Official Exchange
    "BSEIndia",         # Official Exchange
    "CNBCTV18Live",     # Breaking News
    "NDTVProfitIndia"   # Breaking News
]

OUTPUT_FILE = Path(__file__).resolve().parent.parent.parent / 'data' / 'twitter_data.json'

def fetch_tweets(account, hours_back=4):
    """Fetch recent tweets for a specific account using Nitter RSS"""
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours_back)
    
    for instance in NITTER_INSTANCES:
        url = f"{instance}/{account}/rss"
        try:
            response = requests.get(url, headers=headers, timeout=8)
            if response.status_code == 200:
                feed = feedparser.parse(response.content)
                tweets = []
                
                for entry in feed.entries[:10]:
                    # Extract timestamp
                    pub_date = None
                    if hasattr(entry, 'published_parsed') and entry.published_parsed:
                        pub_date = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
                    
                    if pub_date and pub_date < cutoff:
                        continue
                        
                    # Clean up HTML tags from Nitter RSS
                    raw_text = entry.get('title', '')
                    clean_text = re.sub(r'<[^>]+>', '', raw_text)
                    clean_text = re.sub(r'http\S+', '', clean_text).strip()
                    
                    tweets.append({
                        'account': f"@{account}",
                        'text': clean_text,
                        'published': pub_date.isoformat() if pub_date else datetime.now(timezone.utc).isoformat(),
                        'link': entry.get('link', '')
                    })
                return tweets
        except Exception:
            continue # Try the next Nitter instance if one is down
            
    return []

def run_twitter_tracker():
    print("=" * 60)
    print("X/TWITTER TRACKER - FinTwit Firehose")
    print("=" * 60)
    
    all_tweets = []
    for account in TWITTER_ACCOUNTS:
        print(f"[*] Fetching @{account}...")
        tweets = fetch_tweets(account)
        all_tweets.extend(tweets)
        
    # Sort newest first
    all_tweets.sort(key=lambda x: x['published'], reverse=True)
    
    output = {
        'last_updated': datetime.now(timezone.utc).isoformat(),
        'total_tweets': len(all_tweets),
        'tweets': all_tweets
    }
    
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
        
    print("-" * 60)
    print(f"[SUCCESS] Scraped {len(all_tweets)} critical market tweets.")
    print("=" * 60)

if __name__ == "__main__":
    run_twitter_tracker()