"""
NEWS AGGREGATOR
Pulls news from multiple sources, detects sentiment and velocity
Sources: NewsAPI, Marketaux, Finnhub, RSS feeds
"""

import os
import json
import requests
import feedparser
from datetime import datetime, timedelta
from pathlib import Path
from dotenv import load_dotenv
from collections import Counter
import re

env_path = Path(__file__).parent.parent / 'config' / 'keys.env'
load_dotenv(env_path)

NEWS_API_KEY = os.getenv('NEWS_API_KEY')
MARKETAUX_KEY = os.getenv('MARKETAUX_KEY')
FINNHUB_KEY = os.getenv('FINNHUB_KEY')

# ─────────────────────────────────────
# RSS FEEDS - Free, no API key needed
# ─────────────────────────────────────
RSS_FEEDS = {
    'MoneyControl Markets': 'https://www.moneycontrol.com/rss/MCtopnews.xml',
    'MoneyControl Business': 'https://www.moneycontrol.com/rss/business.xml',
    'ET Markets': 'https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms',
    'ET Stocks': 'https://economictimes.indiatimes.com/markets/stocks/rssfeeds/2146842.cms',
    'Mint Markets': 'https://www.livemint.com/rss/markets',
    'Reuters Business': 'https://feeds.reuters.com/reuters/businessNews',
    'CNBC Markets': 'https://www.cnbc.com/id/10000664/device/rss/rss.html',
    'Yahoo Finance': 'https://finance.yahoo.com/news/rssindex',
    'Investing.com': 'https://www.investing.com/rss/news.rss',
    'Bloomberg Markets': 'https://feeds.bloomberg.com/markets/news.rss',
}

# ─────────────────────────────────────
# STOCK KEYWORDS - For mention detection
# ─────────────────────────────────────
INDIAN_STOCK_KEYWORDS = [
    'RELIANCE', 'TCS', 'INFOSYS', 'INFY', 'HDFC', 'ICICI', 'SBI', 'AXIS',
    'KOTAK', 'BAJAJ', 'WIPRO', 'HCLTECH', 'TECH MAHINDRA', 'TATA STEEL',
    'TATA MOTORS', 'MARUTI', 'HINDALCO', 'JSW', 'COAL INDIA', 'ONGC',
    'POWERGRID', 'NTPC', 'ADANI', 'ASIAN PAINTS', 'NESTLE', 'HUL',
    'ITC', 'TITAN', 'SUN PHARMA', 'DR REDDY', 'CIPLA', 'DIVIS',
    'BHARTI AIRTEL', 'VEDANTA', 'GRASIM', 'ULTRACEMCO', 'LARSEN',
    'BAJAJ FINANCE', 'BAJAJ AUTO', 'EICHER', 'BRITANNIA', 'NIFTY', 'SENSEX'
]

US_STOCK_KEYWORDS = [
    'APPLE', 'AAPL', 'MICROSOFT', 'MSFT', 'GOOGLE', 'GOOGL', 'AMAZON',
    'NVIDIA', 'NVDA', 'TESLA', 'TSLA', 'META', 'NETFLIX', 'NFLX',
    'JPMORGAN', 'GOLDMAN', 'BERKSHIRE'
]

SECTOR_KEYWORDS = {
    'IT/Tech': ['IT', 'tech', 'software', 'cloud', 'AI', 'artificial intelligence', 'semiconductor'],
    'Banking': ['bank', 'banking', 'NBFC', 'financial', 'lending', 'loan', 'credit'],
    'Pharma': ['pharma', 'pharmaceutical', 'drug', 'medicine', 'healthcare', 'biotech'],
    'Auto': ['auto', 'automobile', 'car', 'vehicle', 'EV', 'electric vehicle'],
    'Metals': ['steel', 'aluminium', 'copper', 'metal', 'mining'],
    'Energy': ['oil', 'crude', 'gas', 'energy', 'renewable', 'solar'],
    'FMCG': ['FMCG', 'consumer', 'retail', 'food'],
    'Realty': ['realty', 'real estate', 'housing', 'property'],
}


# ─────────────────────────────────────
# FETCH FROM NEWSAPI
# ─────────────────────────────────────
def fetch_newsapi():
    print("\n[NEWSAPI] Fetching...")
    articles = []
    queries = [
        'Indian stock market OR NSE OR BSE OR Nifty OR Sensex',
        'US stock market OR NASDAQ OR S&P 500 OR Wall Street',
        'Federal Reserve OR Fed rate OR interest rate',
        'crude oil OR gold price OR commodity',
    ]
    for query in queries:
        try:
            response = requests.get(
                'https://newsapi.org/v2/everything',
                params={
                    'q': query,
                    'language': 'en',
                    'sortBy': 'publishedAt',
                    'pageSize': 10,
                    'apiKey': NEWS_API_KEY
                },
                timeout=10
            )
            data = response.json()
            if data.get('status') == 'ok':
                for art in data.get('articles', []):
                    articles.append({
                        'source': art.get('source', {}).get('name', 'Unknown'),
                        'source_type': 'NewsAPI',
                        'title': art.get('title', ''),
                        'description': art.get('description', '') or '',
                        'url': art.get('url', ''),
                        'published_at': art.get('publishedAt', ''),
                        'category': query[:30],
                    })
        except Exception as e:
            print(f"  WARN NewsAPI error: {str(e)[:60]}")
    print(f"  Got {len(articles)} articles from NewsAPI")
    return articles


# ─────────────────────────────────────
# FETCH FROM MARKETAUX
# ─────────────────────────────────────
def fetch_marketaux():
    print("\n[MARKETAUX] Fetching...")
    articles = []
    try:
        response = requests.get(
            'https://api.marketaux.com/v1/news/all',
            params={
                'api_token': MARKETAUX_KEY,
                'language': 'en',
                'limit': 25,
                'filter_entities': 'true',
            },
            timeout=10
        )
        data = response.json()
        for art in data.get('data', []):
            articles.append({
                'source': art.get('source', 'Marketaux'),
                'source_type': 'Marketaux',
                'title': art.get('title', ''),
                'description': art.get('description', '') or '',
                'url': art.get('url', ''),
                'published_at': art.get('published_at', ''),
                'sentiment': art.get('sentiment', 0),
                'entities': [e.get('symbol', '') for e in art.get('entities', [])][:5],
            })
        print(f"  Got {len(articles)} articles from Marketaux")
    except Exception as e:
        print(f"  WARN Marketaux error: {str(e)[:60]}")
    return articles


# ─────────────────────────────────────
# FETCH FROM FINNHUB
# ─────────────────────────────────────
def fetch_finnhub():
    print("\n[FINNHUB] Fetching general market news...")
    articles = []
    try:
        response = requests.get(
            'https://finnhub.io/api/v1/news',
            params={'category': 'general', 'token': FINNHUB_KEY},
            timeout=10
        )
        data = response.json()
        if isinstance(data, list):
            for art in data[:30]:
                articles.append({
                    'source': art.get('source', 'Finnhub'),
                    'source_type': 'Finnhub',
                    'title': art.get('headline', ''),
                    'description': art.get('summary', '') or '',
                    'url': art.get('url', ''),
                    'published_at': datetime.fromtimestamp(
                        art.get('datetime', 0)
                    ).isoformat() if art.get('datetime') else '',
                    'category': art.get('category', 'general'),
                })
        print(f"  Got {len(articles)} articles from Finnhub")
    except Exception as e:
        print(f"  WARN Finnhub error: {str(e)[:60]}")
    return articles


# ─────────────────────────────────────
# FETCH FROM RSS FEEDS
# ─────────────────────────────────────
def fetch_rss_feeds():
    print("\n[RSS FEEDS] Fetching from multiple sources...")
    articles = []
    for feed_name, feed_url in RSS_FEEDS.items():
        try:
            feed = feedparser.parse(feed_url)
            count = 0
            for entry in feed.entries[:10]:
                articles.append({
                    'source': feed_name,
                    'source_type': 'RSS',
                    'title': entry.get('title', ''),
                    'description': entry.get('summary', '')[:300] if entry.get('summary') else '',
                    'url': entry.get('link', ''),
                    'published_at': entry.get('published', ''),
                })
                count += 1
            print(f"  {feed_name}: {count} articles")
        except Exception as e:
            print(f"  WARN {feed_name}: {str(e)[:60]}")
    print(f"  Total RSS articles: {len(articles)}")
    return articles


# ─────────────────────────────────────
# DEDUPLICATE ARTICLES
# ─────────────────────────────────────
def deduplicate(articles):
    seen_titles = set()
    unique = []
    for art in articles:
        title = art.get('title', '').strip().lower()
        if not title or len(title) < 10:
            continue
        # Use first 60 chars as fingerprint
        fingerprint = title[:60]
        if fingerprint not in seen_titles:
            seen_titles.add(fingerprint)
            unique.append(art)
    return unique


# ─────────────────────────────────────
# DETECT STOCK MENTIONS
# ─────────────────────────────────────
def detect_stock_mentions(articles):
    mentions = Counter()
    article_to_stocks = {}

    for i, art in enumerate(articles):
        text = (art.get('title', '') + ' ' + art.get('description', '')).upper()
        found_stocks = []

        for stock in INDIAN_STOCK_KEYWORDS + US_STOCK_KEYWORDS:
            # Word boundary match
            pattern = r'\b' + re.escape(stock) + r'\b'
            if re.search(pattern, text):
                mentions[stock] += 1
                found_stocks.append(stock)

        if found_stocks:
            article_to_stocks[i] = found_stocks

    return mentions, article_to_stocks


# ─────────────────────────────────────
# DETECT SECTOR BUZZ
# ─────────────────────────────────────
def detect_sector_buzz(articles):
    sector_counts = Counter()
    for art in articles:
        text = (art.get('title', '') + ' ' + art.get('description', '')).lower()
        for sector, keywords in SECTOR_KEYWORDS.items():
            for kw in keywords:
                if kw.lower() in text:
                    sector_counts[sector] += 1
                    break
    return sector_counts


# ─────────────────────────────────────
# SIMPLE SENTIMENT (no external API)
# ─────────────────────────────────────
POSITIVE_WORDS = ['rally', 'surge', 'soar', 'gain', 'jump', 'rise', 'climb', 'boost',
                  'beat', 'strong', 'growth', 'profit', 'record high', 'bullish',
                  'upgrade', 'positive', 'buy', 'outperform']
NEGATIVE_WORDS = ['crash', 'plunge', 'fall', 'drop', 'tumble', 'slump', 'decline',
                  'loss', 'weak', 'concern', 'worry', 'fear', 'bearish', 'downgrade',
                  'negative', 'sell', 'underperform', 'miss', 'cut', 'warning']

def calculate_sentiment(article):
    text = (article.get('title', '') + ' ' + article.get('description', '')).lower()
    pos = sum(1 for w in POSITIVE_WORDS if w in text)
    neg = sum(1 for w in NEGATIVE_WORDS if w in text)
    if pos == 0 and neg == 0:
        return 'neutral', 0
    score = (pos - neg) / max(pos + neg, 1)
    if score > 0.2:
        return 'positive', score
    elif score < -0.2:
        return 'negative', score
    return 'neutral', score


# ─────────────────────────────────────
# DETECT NEWS VELOCITY
# Same stock mentioned 3+ times in last hour = high velocity
# ─────────────────────────────────────
def detect_velocity(articles, mentions):
    hot_stocks = []
    for stock, count in mentions.most_common(20):
        if count >= 3:
            hot_stocks.append({
                'stock': stock,
                'mention_count': count,
                'velocity': 'HIGH' if count >= 5 else 'MEDIUM'
            })
    return hot_stocks


# ─────────────────────────────────────
# MAIN COLLECTION
# ─────────────────────────────────────
def collect_all_news():
    print("\n" + "=" * 60)
    print("NEWS AGGREGATOR - STARTED")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    all_articles = []

    # Fetch from all sources
    if NEWS_API_KEY:
        all_articles.extend(fetch_newsapi())
    if MARKETAUX_KEY:
        all_articles.extend(fetch_marketaux())
    if FINNHUB_KEY:
        all_articles.extend(fetch_finnhub())

    all_articles.extend(fetch_rss_feeds())

    print(f"\n[TOTAL] Raw articles fetched: {len(all_articles)}")

    # Deduplicate
    unique = deduplicate(all_articles)
    print(f"[DEDUP] Unique articles: {len(unique)}")

    # Add sentiment to each article
    for art in unique:
        sent_label, sent_score = calculate_sentiment(art)
        art['sentiment_label'] = sent_label
        art['sentiment_score'] = round(sent_score, 2)

    # Detect stock mentions
    mentions, article_stocks = detect_stock_mentions(unique)

    # Detect sector buzz
    sector_buzz = detect_sector_buzz(unique)

    # Detect hot stocks (velocity)
    hot_stocks = detect_velocity(unique, mentions)

    # Sentiment distribution
    sentiment_dist = Counter(art['sentiment_label'] for art in unique)

    # Print summary
    print("\n" + "=" * 60)
    print("NEWS INTELLIGENCE SUMMARY")
    print("=" * 60)

    print(f"\nSENTIMENT DISTRIBUTION:")
    for label, count in sentiment_dist.most_common():
        pct = (count / len(unique) * 100) if unique else 0
        print(f"  {label.upper():12s} {count:4d} articles ({pct:.1f}%)")

    print(f"\nTOP MENTIONED STOCKS:")
    for stock, count in mentions.most_common(15):
        print(f"  {stock:20s} {count} mentions")

    print(f"\nSECTOR BUZZ:")
    for sector, count in sector_buzz.most_common(8):
        print(f"  {sector:15s} {count} mentions")

    if hot_stocks:
        print(f"\nHOT STOCKS (HIGH VELOCITY):")
        for hs in hot_stocks[:10]:
            print(f"  [{hs['velocity']}] {hs['stock']} - {hs['mention_count']} mentions")
    else:
        print("\nNo hot stocks detected (no stock mentioned 3+ times)")

    # Save
    output = {
        'timestamp': datetime.now().isoformat(),
        'collection_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'total_articles': len(unique),
        'sentiment_distribution': dict(sentiment_dist),
        'top_stocks': dict(mentions.most_common(20)),
        'sector_buzz': dict(sector_buzz.most_common(10)),
        'hot_stocks': hot_stocks,
        'articles': unique[:100]  # Keep top 100 to limit file size
    }

    data_dir = Path(__file__).parent.parent / 'data'
    data_dir.mkdir(exist_ok=True)
    output_file = data_dir / 'news_feed.json'

    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, default=str, ensure_ascii=True)

    print(f"\nSaved to: {output_file}")
    print("=" * 60 + "\n")

    return output


if __name__ == "__main__":
    print("Starting news aggregator...")
    try:
        collect_all_news()
        print("Done!")
    except Exception as e:
        import traceback
        print(f"ERROR: {e}")
        traceback.print_exc()
