"""
LIVE NEWS TRACKER (Zero Latency)
Instantly scrapes Tier-1 financial RSS feeds for Global & Indian Markets.
Replaces delayed APIs with direct server-to-server XML parsing.
"""

import os
import json
import feedparser
import requests
from datetime import datetime, timedelta, timezone
from pathlib import Path
from collections import Counter
import re

# ============================================================
# TIER-1 INSTANT FEEDS (Global + Indian)
# ============================================================
RSS_FEEDS = {
    'Moneycontrol (Top News)': 'https://www.moneycontrol.com/rss/MCtopnews.xml',
    'Economic Times (Markets)': 'https://economictimes.indiatimes.com/markets/rssfeeds/2146842.cms',
    'LiveMint (Companies)': 'https://www.livemint.com/rss/companies',
    'Yahoo Finance (Global US)': 'https://finance.yahoo.com/news/rssindex',
    'Investing.com (Global Macro)': 'https://in.investing.com/rss/news_285.rss'
}

OUTPUT_FILE = Path(__file__).parent.parent / 'data' / 'live_news_feed.json'

def fetch_feed(name, url, hours_back=4):
    """Fetch and parse a single RSS feed"""
    try:
        # Sneak past firewalls
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code != 200:
            print(f"  [FAIL] {name}: HTTP {response.status_code}")
            return []
            
        feed = feedparser.parse(response.content)
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=hours_back)
        
        articles = []
        for entry in feed.entries[:20]: # Check latest 20 per feed
            # Try to get the published time
            pub_date = None
            if hasattr(entry, 'published_parsed') and entry.published_parsed:
                pub_date = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
            
            # Skip old news
            if pub_date and pub_date < cutoff_time:
                continue
                
            title = entry.get('title', '').strip()
            # Clean HTML out of descriptions
            raw_desc = entry.get('summary', '')
            clean_desc = re.sub('<[^<]+>', '', raw_desc).strip()
            
            articles.append({
                'source': name,
                'title': title,
                'description': clean_desc[:300],
                'link': entry.get('link', ''),
                'published': pub_date.isoformat() if pub_date else datetime.now(timezone.utc).isoformat()
            })
            
        return articles
    except Exception as e:
        print(f"  [ERROR] {name}: {str(e)[:50]}")
        return []

def run_live_news_tracker():
    print("=" * 60)
    print("LIVE NEWS TRACKER - Zero Latency RSS Engine")
    print("=" * 60)
    
    all_articles = []
    
    for name, url in RSS_FEEDS.items():
        print(f"Fetching {name}...")
        articles = fetch_feed(name, url, hours_back=4)
        all_articles.extend(articles)
        print(f"  -> Got {len(articles)} recent breaking stories.")
        
    if not all_articles:
        print("\n[WARN] No breaking news found in the last 4 hours.")
        return
        
    # Sort by newest first
    all_articles.sort(key=lambda x: x['published'], reverse=True)
    
    # Save to JSON
    output = {
        'last_updated': datetime.now(timezone.utc).isoformat(),
        'total_articles': len(all_articles),
        'articles': all_articles
    }
    
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
        
    print("-" * 60)
    print(f"[SUCCESS] Saved {len(all_articles)} live global/local articles.")
    print("=" * 60)

if __name__ == '__main__':
    run_live_news_tracker()