"""
Reddit Sentiment Tracker v2.1 - Bug fixes
Uses Reddit's public JSON endpoints (no API key needed)
Tracks Indian stock market subreddits for retail sentiment

v2.1 Fixes:
- Force UTF-8 stdout (Windows console fix)
- Fix AI sentiment dict-vs-string bug
"""

import sys
import io

# Force UTF-8 stdout on Windows BEFORE any prints
if sys.platform == 'win32':
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
    except Exception:
        pass

import requests
import json
import re
import time
from datetime import datetime, timezone
from collections import Counter
from pathlib import Path

# Import AI router for sentiment analysis
try:
    from ai_router import ask_ai
    AI_AVAILABLE = True
except ImportError:
    AI_AVAILABLE = False
    print("[WARN] ai_router not available, sentiment will be keyword-based only")

# ============================================================
# CONFIGURATION
# ============================================================

SUBREDDITS = [
    'IndianStockMarket',
    'IndiaInvestments',
    'DalalStreetTalks',
    'StockMarketIndia',
]

FETCH_MODES = ['hot', 'new']
POSTS_LIMIT = 50

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'application/json',
    'Accept-Language': 'en-US,en;q=0.9',
    'Accept-Encoding': 'gzip, deflate, br',
    'Connection': 'keep-alive',
}
OUTPUT_FILE = Path(__file__).parent.parent / 'data' / 'reddit_data.json'

# ============================================================
# TICKER UNIVERSE
# ============================================================

NSE_TICKERS = {
    'HDFCBANK', 'ICICIBANK', 'SBIN', 'KOTAKBANK', 'AXISBANK', 'INDUSINDBK',
    'BAJFINANCE', 'BAJAJFINSV',
    'TCS', 'INFY', 'WIPRO', 'HCLTECH', 'TECHM', 'LTIM', 'PERSISTENT', 'COFORGE',
    'RELIANCE', 'ONGC', 'IOC', 'BPCL', 'HPCL', 'GAIL', 'COALINDIA', 'NTPC', 'POWERGRID',
    'TATAMOTORS', 'M&M', 'MARUTI', 'BAJAJ-AUTO', 'EICHERMOT', 'HEROMOTOCO', 'TVSMOTOR',
    'SUNPHARMA', 'DRREDDY', 'CIPLA', 'DIVISLAB', 'LUPIN', 'AUROPHARMA', 'BIOCON',
    'HINDUNILVR', 'ITC', 'NESTLEIND', 'BRITANNIA', 'DABUR', 'GODREJCP', 'MARICO',
    'TATASTEEL', 'JSWSTEEL', 'HINDALCO', 'VEDL', 'JINDALSTEL', 'SAIL', 'NMDC',
    'BHARTIARTL', 'IDEA', 'TATACOMM',
    'ULTRACEMCO', 'SHREECEM', 'ACC', 'AMBUJACEM',
    'ADANIENT', 'ADANIPORTS', 'ADANIPOWER', 'ADANIGREEN',
    'IRCTC', 'IRFC', 'RAILTEL', 'ZOMATO', 'PAYTM', 'NYKAA', 'POLICYBZR',
    'DMART', 'TRENT', 'TITAN', 'ASIANPAINT', 'BERGEPAINT',
    'LT', 'BEL', 'HAL', 'BHEL', 'MAZAGON', 'COCHINSHIP',
    'SUZLON', 'YESBANK', 'IDFCFIRSTB', 'BANDHANBNK', 'PNB', 'BANKBARODA',
    'TATAPOWER', 'JIOFIN', 'LICI', 'PFC', 'RECLTD',
    'NIFTY', 'SENSEX', 'BANKNIFTY', 'FINNIFTY',
}

COMPANY_TO_TICKER = {
    'reliance': 'RELIANCE', 'ril': 'RELIANCE', 'jio': 'RELIANCE',
    'tcs': 'TCS', 'tata consultancy': 'TCS',
    'infosys': 'INFY', 'infy': 'INFY',
    'wipro': 'WIPRO',
    'hcl tech': 'HCLTECH', 'hcltech': 'HCLTECH',
    'tech mahindra': 'TECHM',
    'hdfc bank': 'HDFCBANK', 'hdfcbank': 'HDFCBANK',
    'icici': 'ICICIBANK', 'icici bank': 'ICICIBANK',
    'sbi': 'SBIN', 'state bank': 'SBIN',
    'kotak': 'KOTAKBANK', 'kotak bank': 'KOTAKBANK',
    'axis bank': 'AXISBANK',
    'bajaj finance': 'BAJFINANCE',
    'tata motors': 'TATAMOTORS',
    'maruti': 'MARUTI', 'maruti suzuki': 'MARUTI',
    'mahindra': 'M&M', 'm&m': 'M&M',
    'sun pharma': 'SUNPHARMA',
    'cipla': 'CIPLA',
    'dr reddy': 'DRREDDY', 'dr. reddy': 'DRREDDY',
    'hindustan unilever': 'HINDUNILVR', 'hul': 'HINDUNILVR',
    'itc': 'ITC',
    'nestle': 'NESTLEIND',
    'britannia': 'BRITANNIA',
    'tata steel': 'TATASTEEL',
    'jsw steel': 'JSWSTEEL',
    'hindalco': 'HINDALCO',
    'vedanta': 'VEDL',
    'airtel': 'BHARTIARTL', 'bharti airtel': 'BHARTIARTL',
    'jio financial': 'JIOFIN',
    'adani': 'ADANIENT', 'adani enterprises': 'ADANIENT',
    'adani ports': 'ADANIPORTS',
    'adani power': 'ADANIPOWER',
    'adani green': 'ADANIGREEN',
    'irctc': 'IRCTC',
    'irfc': 'IRFC',
    'zomato': 'ZOMATO',
    'paytm': 'PAYTM',
    'nykaa': 'NYKAA',
    'dmart': 'DMART', 'avenue supermarts': 'DMART',
    'titan': 'TITAN',
    'asian paints': 'ASIANPAINT',
    'l&t': 'LT', 'larsen': 'LT', 'larsen & toubro': 'LT',
    'bel': 'BEL', 'bharat electronics': 'BEL',
    'hal': 'HAL', 'hindustan aeronautics': 'HAL',
    'suzlon': 'SUZLON',
    'yes bank': 'YESBANK',
    'pnb': 'PNB', 'punjab national': 'PNB',
    'tata power': 'TATAPOWER',
    'lic': 'LICI',
    'nifty': 'NIFTY', 'sensex': 'SENSEX', 'bank nifty': 'BANKNIFTY',
    'banknifty': 'BANKNIFTY', 'finnifty': 'FINNIFTY',
}

EXCLUDE_WORDS = {'I', 'A', 'THE', 'OK', 'NEW', 'FOR', 'WHO', 'CEO',
                 'GST', 'RBI', 'SEBI', 'FII', 'DII', 'NSE', 'BSE', 'PE', 'PB',
                 'EPS', 'YOY', 'QOQ', 'YTD', 'ATH', 'ATL', 'EOD', 'WTF', 'IMO',
                 'TLDR', 'OP', 'EDIT', 'AM', 'PM', 'US', 'UK', 'UAE', 'IPO', 'AI'}

# ============================================================
# RELEVANCE FILTER
# ============================================================

IRRELEVANT_KEYWORDS = ['meme', 'shitpost', 'roast', 'dating', 'relationship']

def is_relevant(post):
    text = (post.get('title', '') + ' ' + post.get('selftext', '')).lower()
    if any(kw in text for kw in IRRELEVANT_KEYWORDS):
        return False
    if post.get('score', 0) < 3:
        return False
    return True

# ============================================================
# REDDIT JSON FETCHER
# ============================================================

def fetch_subreddit_posts(subreddit, mode='hot', limit=50):
    url = f"https://old.reddit.com/r/{subreddit}/{mode}.json?limit={limit}"
    
    try:
        response = requests.get(url, headers=HEADERS, timeout=15)
        if response.status_code == 429:
            print(f"[WARN] Rate limited on r/{subreddit}, sleeping 30s...")
            time.sleep(30)
            response = requests.get(url, headers=HEADERS, timeout=15)
        
        if response.status_code != 200:
            print(f"[ERROR] r/{subreddit} returned {response.status_code}")
            return []
        
        data = response.json()
        posts = []
        
        for child in data.get('data', {}).get('children', []):
            p = child.get('data', {})
            posts.append({
                'id': p.get('id'),
                'subreddit': p.get('subreddit'),
                'title': p.get('title', ''),
                'selftext': p.get('selftext', '')[:1000],
                'score': p.get('score', 0),
                'upvote_ratio': p.get('upvote_ratio', 0),
                'num_comments': p.get('num_comments', 0),
                'created_utc': p.get('created_utc', 0),
                'url': f"https://reddit.com{p.get('permalink', '')}",
                'author': p.get('author', '[deleted]'),
                'flair': p.get('link_flair_text', ''),
            })
        
        return posts
    
    except Exception as e:
        print(f"[ERROR] Failed to fetch r/{subreddit}/{mode}: {e}")
        return []

# ============================================================
# TICKER EXTRACTION
# ============================================================

def extract_tickers(text):
    if not text:
        return []
    
    found = set()
    text_lower = text.lower()
    
    candidates = re.findall(r'\b[A-Z][A-Z0-9&-]{2,14}\b', text)
    for c in candidates:
        if c in EXCLUDE_WORDS:
            continue
        if c in NSE_TICKERS:
            found.add(c)
    
    for company_name, ticker in COMPANY_TO_TICKER.items():
        if re.search(r'\b' + re.escape(company_name) + r'\b', text_lower):
            found.add(ticker)
    
    return list(found)

def count_ticker_mentions(posts):
    counter = Counter()
    ticker_posts = {}
    
    for post in posts:
        text = post.get('title', '') + ' ' + post.get('selftext', '')
        tickers = extract_tickers(text)
        
        for ticker in set(tickers):
            counter[ticker] += 1
            if ticker not in ticker_posts:
                ticker_posts[ticker] = []
            ticker_posts[ticker].append(post)
    
    return counter, ticker_posts

# ============================================================
# SENTIMENT ANALYSIS
# ============================================================

STRONG_BEARISH = ['bloodbath', 'crash', 'panic', 'wiped out', 'plummet',
                  'collapse', 'tank', 'capitulate', 'doomed', 'avoid',
                  'disaster', 'meltdown', 'nightmare', 'carnage']

BEARISH_WORDS = ['sell', 'short', 'bearish', 'dump', 'overvalued',
                 'red', 'loss', 'downside', 'weak', 'negative',
                 'breakdown', 'fear', 'bubble', 'correction', 'fall', 'drop']

STRONG_BULLISH = ['multibagger', 'breakout', 'rally', 'surge', 'soar',
                  'rocket', 'undervalued', 'accumulate', 'moon']

BULLISH_WORDS = ['buy', 'long', 'bullish', 'gains', 'profit',
                 'target', 'upside', 'strong', 'positive', 'green',
                 'momentum', 'opportunity', 'rise', 'up']

def keyword_sentiment(text):
    text_lower = text.lower()
    
    bull = sum(1 for w in BULLISH_WORDS if w in text_lower)
    bull += sum(2 for w in STRONG_BULLISH if w in text_lower)
    
    bear = sum(1 for w in BEARISH_WORDS if w in text_lower)
    bear += sum(2 for w in STRONG_BEARISH if w in text_lower)
    
    if bull == 0 and bear == 0:
        return 'neutral', 0.5
    
    score = bull / (bull + bear)
    if score >= 0.6:
        return 'bullish', score
    elif score <= 0.4:
        return 'bearish', score
    return 'neutral', score


def ai_sentiment_summary(posts, ticker=None):
    """Use AI (Gemini) to summarize sentiment - v2.1 fixed dict bug"""
    if not AI_AVAILABLE or not posts:
        return None
    
    sample = posts[:8]
    text_blob = "\n".join([
        f"- [{p['score']} upvotes] {p['title']}" 
        for p in sample
    ])
    
    target = f"about {ticker}" if ticker else "Indian stock market"
    
    prompt = f"""Analyze these Reddit posts {target} and respond in EXACTLY this JSON format:
{{"sentiment":"bullish|bearish|neutral","confidence":0-100,"summary":"one-line takeaway","themes":["theme1","theme2"]}}

Posts:
{text_blob}

Respond with ONLY the JSON, no other text."""
    
    try:
        result = ask_ai(prompt, use_case='translate', max_tokens=300)
        
        # FIX v2.1: ask_ai returns a dict like {'success': True, 'text': '...', 'model': '...'}
        # We need to extract the 'text' field, not regex the whole dict
        if not isinstance(result, dict):
            return None
        
        if not result.get('success'):
            return None
        
        response_text = result.get('text', '')
        if not isinstance(response_text, str):
            return None
        
        # Extract JSON from response text
        match = re.search(r'\{.*\}', response_text, re.DOTALL)
        if match:
            return json.loads(match.group())
    except Exception as e:
        print(f"[WARN] AI sentiment failed: {e}")
    
    return None

# ============================================================
# MAIN AGGREGATOR
# ============================================================

def run_reddit_tracker():
    print("=" * 60)
    print("REDDIT TRACKER v2.1 - Indian Stock Market Sentiment")
    print("=" * 60)
    
    all_posts = []
    
    for sub in SUBREDDITS:
        for mode in FETCH_MODES:
            print(f"[FETCH] r/{sub}/{mode}...")
            posts = fetch_subreddit_posts(sub, mode, POSTS_LIMIT)
            all_posts.extend(posts)
            time.sleep(2)
    
    seen = set()
    unique_posts = []
    for p in all_posts:
        if p['id'] not in seen:
            seen.add(p['id'])
            unique_posts.append(p)
    
    print(f"[INFO] Fetched {len(unique_posts)} unique posts")
    
    relevant_posts = [p for p in unique_posts if is_relevant(p)]
    print(f"[INFO] {len(relevant_posts)} trading-relevant posts")
    
    ticker_counter, ticker_posts = count_ticker_mentions(relevant_posts)
    top_tickers = ticker_counter.most_common(15)
    
    trending_tickers = []
    for ticker, count in top_tickers:
        posts_for_ticker = ticker_posts[ticker]
        top_post = max(posts_for_ticker, key=lambda x: x['score'])
        
        all_text = " ".join([p['title'] + " " + p.get('selftext', '') 
                             for p in posts_for_ticker])
        sent_label, sent_score = keyword_sentiment(all_text)
        
        trending_tickers.append({
            'ticker': ticker,
            'mentions': count,
            'sentiment': sent_label,
            'sentiment_score': round(sent_score, 2),
            'top_post': {
                'title': top_post['title'],
                'url': top_post['url'],
                'score': top_post['score'],
                'comments': top_post['num_comments'],
                'subreddit': top_post['subreddit'],
            }
        })
    
    hot_discussions = sorted(relevant_posts, 
                             key=lambda x: x['score'] + x['num_comments'] * 2, 
                             reverse=True)[:10]
    
    hot_list = []
    for p in hot_discussions:
        sent_label, sent_score = keyword_sentiment(p['title'] + " " + p.get('selftext', ''))
        hot_list.append({
            'title': p['title'],
            'subreddit': p['subreddit'],
            'score': p['score'],
            'comments': p['num_comments'],
            'url': p['url'],
            'flair': p['flair'],
            'sentiment': sent_label,
            'tickers': list(set(extract_tickers(p['title'] + " " + p.get('selftext', '')))),
        })
    
    market_mood = ai_sentiment_summary(hot_discussions[:10])
    if not market_mood:
        all_titles = " ".join([p['title'] for p in hot_discussions])
        label, score = keyword_sentiment(all_titles)
        market_mood = {
            'sentiment': label,
            'confidence': int(score * 100),
            'summary': f"Aggregated keyword sentiment: {label}",
            'themes': []
        }
    
    output = {
        'last_updated': datetime.now(timezone.utc).isoformat(),
        'total_posts_analyzed': len(relevant_posts),
        'subreddits_scanned': SUBREDDITS,
        'market_mood': market_mood,
        'trending_tickers': trending_tickers,
        'hot_discussions': hot_list,
    }
    
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    
    print(f"[OK] Saved {OUTPUT_FILE}")
    print(f"[INFO] Top 5 trending: {[t['ticker'] for t in trending_tickers[:5]]}")
    print(f"[INFO] Market mood: {market_mood.get('sentiment')}")
    print("=" * 60)
    
    return output


if __name__ == '__main__':
    run_reddit_tracker()