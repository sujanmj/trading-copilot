"""
INSHORTS TRACKER v3 - With trading-relevance filter
Removes celebrity/movies/sports/death news
Keeps only market-relevant content
"""

import os
import json
import re
import requests
from datetime import datetime
from pathlib import Path
from collections import Counter
from bs4 import BeautifulSoup

DATA_DIR = Path(__file__).parent.parent / 'data'
DATA_DIR.mkdir(exist_ok=True)


CATEGORIES = {
    'top_stories': '',
    'business': 'business',
    'national': 'national',
    'world': 'world',
    'politics': 'politics',
}


# ─────────────────────────────────────
# RELEVANCE KEYWORDS - Must have AT LEAST ONE of these
# ─────────────────────────────────────
RELEVANT_KEYWORDS = [
    # Markets
    'stock', 'stocks', 'share', 'shares', 'sensex', 'nifty', 'bse', 'nse',
    'market', 'markets', 'trader', 'trading', 'investor', 'investment',
    'ipo', 'listing', 'mutual fund', 'sip', 'fii', 'fpi', 'dii',
    'rally', 'crash', 'bull', 'bear', 'correction', 'breakout',

    # Economy
    'economy', 'gdp', 'inflation', 'cpi', 'wpi', 'rbi', 'sebi', 'mpc',
    'rate', 'repo', 'fiscal', 'budget', 'tax', 'gst', 'subsidy',
    'fdi', 'fii', 'currency', 'rupee', 'dollar', 'forex',

    # Companies & Sectors
    'reliance', 'tata', 'adani', 'ambani', 'infosys', 'tcs', 'wipro',
    'hdfc', 'icici', 'sbi', 'kotak', 'axis', 'maruti', 'bajaj',
    'pharma', 'banking', 'auto', 'fintech', 'fmcg', 'realty',
    'telecom', 'metals', 'cement', 'oil', 'gas', 'energy',

    # Commodities & Materials
    'gold', 'silver', 'crude', 'petrol', 'diesel', 'lpg',
    'aluminium', 'steel', 'copper', 'commodity',

    # Geopolitics affecting markets
    'iran', 'israel', 'russia', 'ukraine', 'china', 'sanctions',
    'tariff', 'trade war', 'fed', 'federal reserve', 'opec',

    # Government / Policy
    'modi', 'sitharaman', 'finance minister', 'pm modi', 'cabinet',
    'policy', 'reform', 'amendment', 'announcement', 'scheme',
    'pli scheme', 'production', 'manufacturing', 'export', 'import',

    # Business events
    'merger', 'acquisition', 'earnings', 'profit', 'revenue', 'quarterly',
    'q1', 'q2', 'q3', 'q4', 'fy', 'dividend', 'bonus', 'split',
    'buyback', 'rights issue',

    # International markets
    'wall street', 'nasdaq', 'dow jones', 's&p', 'apple', 'tesla',
    'nvidia', 'microsoft', 'amazon', 'google', 'meta',

    # Crypto/digital
    'bitcoin', 'crypto', 'cryptocurrency',
]


# ─────────────────────────────────────
# IRRELEVANT KEYWORDS - Must NOT have these (celebrity, sports, etc.)
# ─────────────────────────────────────
IRRELEVANT_KEYWORDS = [
    # Celebrity / Entertainment
    'actor', 'actress', 'film', 'movie', 'bollywood', 'hollywood',
    'singer', 'rapper', 'celebrity', 'star kid', 'photoshoot',
    'music video', 'album', 'concert', 'wedding', 'engagement',
    'divorce', 'affair', 'dating', 'birthday', 'anniversary',
    'fashion', 'red carpet', 'awards show', 'reality show',
    'web series', 'netflix series', 'amazon prime',

    # Sports (unless stock-related)
    'cricket', 'ipl', 'football', 'fifa', 'olympics', 'wimbledon',
    'tournament', 'match', 'wicket', 'goal', 'champion',
    'kohli', 'rohit sharma', 'dhoni', 'messi', 'ronaldo',

    # Crime / Tragedy (generally not market-moving)
    'murder', 'rape', 'assault', 'robbery', 'kidnap',
    'suicide', 'died at', 'passes away', 'death of',
    'hospitalized', 'arrested for',

    # Personal / Lifestyle
    'recipe', 'horoscope', 'astrology', 'zodiac', 'fashion tips',
    'beauty tips', 'skincare', 'haircare', 'workout', 'yoga',
    'travel guide', 'tourist', 'restaurant',

    # Religious / Cultural events (unless economy)
    'temple visit', 'pilgrimage', 'festival celebration',
    'devotion', 'spiritual', 'puja', 'religious ceremony',

    # Routine entertainment
    'viral video', 'viral photo', 'tweets', 'instagram post',
    'twitter post', 'memes',
]


STOCK_KEYWORDS = [
    'RELIANCE', 'TCS', 'INFOSYS', 'INFY', 'HDFC', 'ICICI', 'SBI', 'AXIS',
    'KOTAK', 'BAJAJ', 'WIPRO', 'HCLTECH', 'TATA STEEL', 'TATA MOTORS',
    'MARUTI', 'ADANI', 'NESTLE', 'HUL', 'ITC', 'TITAN', 'SUN PHARMA',
    'BHARTI AIRTEL', 'VEDANTA', 'NIFTY', 'SENSEX', 'BANK NIFTY',
    'GOLD', 'SILVER', 'CRUDE', 'OIL', 'BITCOIN', 'IPO', 'FED', 'RBI',
    'MODI', 'SITHARAMAN'
]


SECTOR_KEYWORDS = {
    'IT/Tech': ['IT', 'tech', 'software', 'AI', 'semiconductor'],
    'Banking': ['bank', 'banking', 'NBFC', 'lending'],
    'Pharma': ['pharma', 'drug', 'medicine'],
    'Auto': ['auto', 'EV', 'car', 'vehicle'],
    'Energy': ['oil', 'crude', 'gas', 'petrol', 'diesel'],
    'Metals': ['steel', 'aluminium', 'metal'],
    'FMCG': ['FMCG', 'consumer'],
}


def is_trading_relevant(item):
    """Check if a story is relevant to trading/markets"""
    text = (item.get('title', '') + ' ' + item.get('content', '')).lower()

    if not text or len(text) < 10:
        return False

    # Skip generic site descriptions
    if 'short english & hindi news' in text:
        return False
    if 'photo gallery' in text:
        return False

    # Count irrelevant keywords - if too many, REJECT
    irrelevant_score = 0
    for kw in IRRELEVANT_KEYWORDS:
        if kw.lower() in text:
            irrelevant_score += 1

    # Count relevant keywords
    relevant_score = 0
    matched_kws = []
    for kw in RELEVANT_KEYWORDS:
        if kw.lower() in text:
            relevant_score += 1
            matched_kws.append(kw)

    # Decision logic:
    # - If 3+ irrelevant keywords AND less than relevant → REJECT
    # - If at least 1 relevant keyword → ACCEPT
    # - Otherwise → REJECT (no signal)

    if irrelevant_score >= 3 and irrelevant_score > relevant_score:
        return False

    return relevant_score >= 1


def fetch_inshorts_page(category):
    """Scrape Inshorts page directly"""
    try:
        url = f"https://inshorts.com/en/read/{category}" if category else "https://inshorts.com/en/read"

        response = requests.get(url, timeout=15, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        })

        if response.status_code != 200:
            return []

        soup = BeautifulSoup(response.content, 'lxml')
        items = []

        # Try Next.js JSON
        next_data = soup.find('script', {'id': '__NEXT_DATA__'})
        if next_data:
            try:
                json_data = json.loads(next_data.string)
                page_props = json_data.get('props', {}).get('pageProps', {})
                news_list = (
                    page_props.get('newsList', []) or
                    page_props.get('initialNews', []) or
                    page_props.get('news', []) or
                    page_props.get('data', {}).get('news_list', [])
                )

                for entry in news_list[:30]:
                    news_obj = entry.get('news_obj', entry)
                    if not news_obj or not news_obj.get('title'):
                        continue
                    items.append({
                        'category': (category or 'TOP').upper(),
                        'title': news_obj.get('title', '').strip(),
                        'content': news_obj.get('content', '').strip(),
                        'author': news_obj.get('author_name', '')[:50],
                        'source_url': news_obj.get('source_url', ''),
                        'source_name': news_obj.get('source_name', 'Inshorts'),
                        'shortened_url': news_obj.get('shortened_url', ''),
                    })

                if items:
                    return items
            except:
                pass

        return items

    except Exception as e:
        return []


def fetch_google_news_finance():
    """Fetch ONLY finance/business news from Google News"""
    try:
        import feedparser

        # Multiple targeted queries for trading-relevant news
        queries = [
            'site:inshorts.com (stock OR market OR economy OR sensex OR nifty)',
            'Indian stock market today',
            'Sensex Nifty news',
            'RBI interest rate India',
            'Indian economy news',
        ]

        all_items = []
        seen = set()

        for query in queries:
            url = f'https://news.google.com/rss/search?q={query.replace(" ", "+")}&hl=en-IN&gl=IN&ceid=IN:en'

            try:
                feed = feedparser.parse(url)
                for entry in feed.entries[:20]:
                    title = entry.get('title', '').strip()
                    # Remove source suffix like "- Inshorts"
                    title = re.sub(r'\s*-\s*[\w\s.]+$', '', title)

                    if not title or title in seen:
                        continue
                    seen.add(title)

                    all_items.append({
                        'category': 'BUSINESS',
                        'title': title,
                        'content': entry.get('summary', '')[:300],
                        'author': '',
                        'source_url': entry.get('link', ''),
                        'source_name': 'Google News',
                        'shortened_url': '',
                    })
            except:
                continue

        return all_items

    except Exception as e:
        print(f"  WARN Google News: {str(e)[:60]}")
        return []


def detect_stock_mentions(items):
    mentions = Counter()
    for item in items:
        text = (item.get('title', '') + ' ' + item.get('content', '')).upper()
        for stock in STOCK_KEYWORDS:
            pattern = r'\b' + re.escape(stock) + r'\b'
            if re.search(pattern, text):
                mentions[stock] += 1
    return mentions


def detect_sector_buzz(items):
    sector_counts = Counter()
    for item in items:
        text = (item.get('title', '') + ' ' + item.get('content', '')).lower()
        for sector, keywords in SECTOR_KEYWORDS.items():
            for kw in keywords:
                if kw.lower() in text:
                    sector_counts[sector] += 1
                    break
    return sector_counts


def calculate_sentiment(text):
    text_lower = text.lower()
    positive = ['rally', 'surge', 'gain', 'rise', 'profit', 'growth', 'boost', 'beat', 'strong']
    negative = ['crash', 'fall', 'drop', 'loss', 'decline', 'concern', 'fear', 'cut', 'weak']
    pos = sum(1 for w in positive if w in text_lower)
    neg = sum(1 for w in negative if w in text_lower)
    if pos > neg and pos > 0:
        return 'positive'
    elif neg > pos:
        return 'negative'
    return 'neutral'


def collect_inshorts():
    print("\n" + "=" * 60)
    print("INSHORTS TRACKER v3 - WITH RELEVANCE FILTER")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    print("\n[FETCHING] Inshorts pages...")
    print("-" * 60)

    raw_items = []
    seen_titles = set()

    for cat_name, cat_slug in CATEGORIES.items():
        items = fetch_inshorts_page(cat_slug)
        unique = []
        for item in items:
            title_key = item.get('title', '').lower()[:80]
            if title_key and title_key not in seen_titles:
                seen_titles.add(title_key)
                unique.append(item)
        print(f"  {cat_name.upper():15s} {len(unique):3d} stories")
        raw_items.extend(unique)

    if len(raw_items) < 5:
        print("\n[FALLBACK] Using Google News for finance topics...")
        google_items = fetch_google_news_finance()
        for item in google_items:
            title_key = item.get('title', '').lower()[:80]
            if title_key and title_key not in seen_titles:
                seen_titles.add(title_key)
                raw_items.append(item)
        print(f"  Google News (filtered queries): {len(google_items)} stories")

    print(f"\n[RAW TOTAL] {len(raw_items)} stories before filter")

    if not raw_items:
        print("\nWARN: No stories fetched")
        return None

    # ─── APPLY RELEVANCE FILTER ───
    print("\n[FILTERING] Removing celebrity/sports/non-market content...")
    relevant = []
    rejected_count = 0

    for item in raw_items:
        if is_trading_relevant(item):
            relevant.append(item)
        else:
            rejected_count += 1

    print(f"  Filtered out: {rejected_count} non-relevant stories")
    print(f"  Kept: {len(relevant)} trading-relevant stories")

    if not relevant:
        print("\nWARN: All stories rejected by filter. Saving empty.")
        relevant = []

    # Add sentiment
    for item in relevant:
        text = item.get('title', '') + ' ' + item.get('content', '')
        item['sentiment'] = calculate_sentiment(text)

    mentions = detect_stock_mentions(relevant)
    sectors = detect_sector_buzz(relevant)
    sentiment_dist = Counter(i['sentiment'] for i in relevant)

    print("\n" + "=" * 60)
    print("INSHORTS INTELLIGENCE (FILTERED)")
    print("=" * 60)

    if relevant:
        print(f"\nSENTIMENT:")
        for label, count in sentiment_dist.most_common():
            pct = (count / len(relevant) * 100)
            print(f"  {label.upper():12s} {count:3d} ({pct:.1f}%)")

        if mentions:
            print(f"\nTOP MENTIONS:")
            for stock, count in mentions.most_common(15):
                print(f"  {stock:20s} {count}x")

        if sectors:
            print(f"\nSECTOR BUZZ:")
            for sector, count in sectors.most_common(8):
                print(f"  {sector:15s} {count} mentions")

        print(f"\nSAMPLE HEADLINES (top 10):")
        for item in relevant[:10]:
            print(f"  [{item['category'][:8]}] {item['title'][:80]}")

    # Save
    output = {
        'timestamp': datetime.now().isoformat(),
        'collection_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'total_stories': len(relevant),
        'rejected_count': rejected_count,
        'sentiment_distribution': dict(sentiment_dist),
        'top_mentions': dict(mentions.most_common(20)),
        'sector_buzz': dict(sectors.most_common(10)),
        'stories': relevant[:80]
    }

    output_file = DATA_DIR / 'inshorts_feed.json'
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, default=str, ensure_ascii=False)

    print(f"\nSaved to: {output_file}")
    print("=" * 60 + "\n")
    return output


if __name__ == "__main__":
    print("Starting Inshorts Tracker v3...")
    try:
        collect_inshorts()
        print("Done!")
    except Exception as e:
        import traceback
        print(f"ERROR: {e}")
        traceback.print_exc()