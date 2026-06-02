"""
LIVE NEWS TRACKER (Zero Latency)
Instantly scrapes Tier-1 financial RSS feeds for Global & Indian Markets.
Writes to news_feed.json (used by master_analyzer) and live_news_feed.json.
"""

import os
import json
import traceback
import feedparser
import requests
from datetime import datetime, timedelta, timezone
from pathlib import Path
from collections import Counter
import re

from backend.storage.json_io import atomic_write_json

RSS_FEEDS = {
    'Economic Times (Markets)': 'https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms',
    'Economic Times (Markets Alt)': 'https://economictimes.indiatimes.com/markets/rssfeeds/2146842.cms',
    'Business Standard Markets': 'https://www.business-standard.com/rss/markets-106.rss',
    'NDTV Profit': 'https://feeds.feedburner.com/ndtvprofit-latest',
    'LiveMint (Companies)': 'https://www.livemint.com/rss/companies',
    'Yahoo Finance (Global US)': 'https://finance.yahoo.com/news/rssindex',
    'Investing.com (Global Macro)': 'https://in.investing.com/rss/news_285.rss',
}

DATA_DIR = Path(__file__).resolve().parent.parent.parent / 'data'
OUTPUT_FILE = DATA_DIR / 'news_feed.json'
OUTPUT_FILE_ALT = DATA_DIR / 'live_news_feed.json'

FEED_STATS = {'ok': 0, 'fail': 0}


def fetch_feed(name, url, hours_back=24):
    """Fetch and parse a single RSS feed with detailed logging."""
    try:
        print(f"  [FETCH] {name}")
        print(f"          URL: {url}")
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        response = requests.get(url, headers=headers, timeout=15)

        if response.status_code != 200:
            print(f"  [FAIL] {name}: HTTP {response.status_code}")
            FEED_STATS['fail'] += 1
            return []

        feed = feedparser.parse(response.content)
        if feed.bozo and feed.bozo_exception:
            print(f"  [WARN] {name}: parse warning — {feed.bozo_exception}")

        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=hours_back)
        articles = []

        for entry in feed.entries[:25]:
            pub_date = None
            if hasattr(entry, 'published_parsed') and entry.published_parsed:
                pub_date = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)

            if pub_date and pub_date < cutoff_time:
                continue

            title = entry.get('title', '').strip()
            raw_desc = entry.get('summary', '')
            clean_desc = re.sub(r'<[^<]+>', '', raw_desc).strip()

            articles.append({
                'source': name,
                'title': title,
                'description': clean_desc[:300],
                'link': entry.get('link', ''),
                'published': pub_date.isoformat() if pub_date else datetime.now(timezone.utc).isoformat(),
                'sentiment_label': 'neutral',
            })

        print(f"  [OK] {name}: {len(articles)} articles")
        FEED_STATS['ok'] += 1
        return articles

    except Exception as e:
        print(f"  [FAIL] {name}: {e}")
        traceback.print_exc()
        FEED_STATS['fail'] += 1
        return []


def save_news_output(all_articles, feed_results):
    """Save partial or full results to both output files."""
    all_articles.sort(key=lambda x: x.get('published', ''), reverse=True)

    output = {
        'last_updated': datetime.now(timezone.utc).isoformat(),
        'total_articles': len(all_articles),
        'feeds_ok': FEED_STATS['ok'],
        'feeds_failed': FEED_STATS['fail'],
        'feed_results': feed_results,
        'articles': all_articles,
    }

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    for path in (OUTPUT_FILE, OUTPUT_FILE_ALT):
        atomic_write_json(path, output)
        print(f"[SAVED] {path}")


def run_live_news_tracker():
    print("=" * 60)
    print("LIVE NEWS TRACKER - RSS Engine")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    global FEED_STATS
    FEED_STATS = {'ok': 0, 'fail': 0}

    all_articles = []
    feed_results = {}

    for name, url in RSS_FEEDS.items():
        articles = fetch_feed(name, url, hours_back=24)
        feed_results[name] = {'count': len(articles), 'status': 'ok' if articles else 'empty'}
        all_articles.extend(articles)

    print("-" * 60)
    print(f"Feeds OK: {FEED_STATS['ok']} | Feeds failed/empty: {FEED_STATS['fail']}")
    print(f"Total articles collected: {len(all_articles)}")

    if not all_articles:
        print("[WARN] No articles collected — saving empty news_feed.json anyway")
        save_news_output([], feed_results)
        return

    save_news_output(all_articles, feed_results)
    print("=" * 60)


if __name__ == '__main__':
    try:
        run_live_news_tracker()
    except Exception as e:
        print(f"[FATAL] live_news_tracker crashed: {e}")
        traceback.print_exc()
        try:
            save_news_output([], {'error': str(e)})
        except Exception:
            pass
