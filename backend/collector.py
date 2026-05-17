"""
INDIAN MARKET COLLECTOR
Fetches Indian stock prices and market news
Clean ASCII version for subprocess compatibility
"""

import requests
import json
import os
import yfinance as yf
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

env_path = Path(__file__).parent.parent / 'config' / 'keys.env'
load_dotenv(env_path)

NEWS_API_KEY = os.getenv('NEWS_API_KEY')

WATCHLIST = {
    'RELIANCE':  'RELIANCE.NS',
    'HDFC BANK': 'HDFCBANK.NS',
    'INFOSYS':   'INFY.NS',
    'TCS':       'TCS.NS',
    'TATA STEEL':'TATASTEEL.NS',
    'GOLD ETF':  'GOLDBEES.NS',
    'SILVER ETF':'SILVERBEES.NS',
    'NIFTY 50':  '^NSEI',
    'SENSEX':    '^BSESN'
}


def fetch_market_news():
    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Fetching Indian market news...")
    try:
        url = "https://newsapi.org/v2/everything"
        params = {
            'q': 'NSE OR BSE OR Nifty OR Sensex OR Indian stocks OR SEBI',
            'language': 'en',
            'sortBy': 'publishedAt',
            'pageSize': 20,
            'apiKey': NEWS_API_KEY
        }
        response = requests.get(url, params=params, timeout=10)
        data = response.json()
        if data.get('status') == 'ok':
            print(f"OK Fetched {len(data['articles'])} market news articles")
            return data['articles']
        else:
            print(f"WARN News API error: {data.get('message', 'Unknown error')}")
            return []
    except Exception as e:
        print(f"WARN Failed to fetch market news: {e}")
        return []


def fetch_global_news():
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Fetching global market news...")
    try:
        url = "https://newsapi.org/v2/everything"
        params = {
            'q': 'Federal Reserve OR NASDAQ OR Wall Street OR crude oil OR gold price OR US economy',
            'language': 'en',
            'sortBy': 'publishedAt',
            'pageSize': 15,
            'apiKey': NEWS_API_KEY
        }
        response = requests.get(url, params=params, timeout=10)
        data = response.json()
        if data.get('status') == 'ok':
            print(f"OK Fetched {len(data['articles'])} global news articles")
            return data['articles']
        else:
            print(f"WARN Global news error: {data.get('message')}")
            return []
    except Exception as e:
        print(f"WARN Failed to fetch global news: {e}")
        return []


def fetch_stock_price(name, yahoo_symbol):
    try:
        ticker = yf.Ticker(yahoo_symbol)
        info = ticker.fast_info
        last_price = info.last_price
        prev_close = info.previous_close
        change = last_price - prev_close
        change_pct = (change / prev_close) * 100
        return {
            'name': name,
            'symbol': yahoo_symbol,
            'price': round(last_price, 2),
            'change': round(change, 2),
            'change_percent': round(change_pct, 2),
            'timestamp': datetime.now().strftime('%H:%M:%S')
        }
    except Exception as e:
        print(f"WARN Failed to fetch {name}: {str(e)[:60]}")
        return None


def fetch_all_prices():
    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Fetching stock prices...")
    prices = {}
    for name, symbol in WATCHLIST.items():
        data = fetch_stock_price(name, symbol)
        if data:
            prices[name] = data
            arrow = "UP  " if data['change_percent'] >= 0 else "DOWN"
            print(f"  {arrow} {name:12s} Rs.{data['price']:>10,.2f} ({data['change_percent']:+.2f}%)")
        else:
            print(f"  WARN {name}: Could not fetch")
    return prices


def save_data(news, global_news, prices):
    data = {
        'timestamp': datetime.now().isoformat(),
        'market_news': news,
        'global_news': global_news,
        'prices': prices
    }
    data_dir = Path(__file__).parent.parent / 'data'
    data_dir.mkdir(exist_ok=True)
    output_file = data_dir / 'latest_market_data.json'
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, default=str, ensure_ascii=True)
    print(f"\nSaved to: {output_file}")


def collect_all():
    print("\n" + "=" * 50)
    print("COLLECTING INDIAN MARKET DATA")
    print("=" * 50)
    news = fetch_market_news()
    global_news = fetch_global_news()
    prices = fetch_all_prices()
    save_data(news, global_news, prices)
    print("=" * 50)
    print("Collection complete.")
    print("=" * 50)


if __name__ == "__main__":
    print("Trading Copilot - Indian Market Data Collector")
    print(f"Watching {len(WATCHLIST)} symbols")
    print(f"News API Key: {'OK Loaded' if NEWS_API_KEY else 'MISSING - check keys.env'}")
    collect_all()