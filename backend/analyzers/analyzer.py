"""
BASIC INDIAN MARKET ANALYZER
Sends Indian market data to Claude for quick analysis
Clean ASCII version
"""

import json
import os
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
import anthropic

env_path = Path(__file__).resolve().parent.parent.parent / 'config' / 'keys.env'
load_dotenv(env_path)

ANTHROPIC_API_KEY = os.getenv('ANTHROPIC_API_KEY')
client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


def load_market_data():
    data_file = Path(__file__).resolve().parent.parent.parent / 'data' / 'latest_market_data.json'
    if not data_file.exists():
        print("ERROR: No market data found. Run collector.py first.")
        return None
    with open(data_file, 'r', encoding='utf-8') as f:
        return json.load(f)


def format_prices_for_claude(prices):
    lines = []
    for name, data in prices.items():
        arrow = "UP" if data['change_percent'] >= 0 else "DOWN"
        lines.append(f"{name}: Rs.{data['price']} {arrow} {data['change_percent']:+.2f}%")
    return "\n".join(lines)


def format_news_for_claude(articles, max_articles=10):
    lines = []
    for i, article in enumerate(articles[:max_articles]):
        title = article.get('title', 'No title')
        source = article.get('source', {}).get('name', 'Unknown')
        published = article.get('publishedAt', '')[:16].replace('T', ' ')
        lines.append(f"- [{source}] {title} ({published})")
    return "\n".join(lines)


def analyze_market():
    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Analyzing market with Claude...")

    data = load_market_data()
    if not data:
        return None

    prices_text = format_prices_for_claude(data.get('prices', {}))
    market_news_text = format_news_for_claude(data.get('market_news', []))
    global_news_text = format_news_for_claude(data.get('global_news', []))

    prompt = f"""You are an expert Indian stock market analyst. Analyze the data below.

CURRENT PRICES (NSE/BSE):
{prices_text}

INDIAN MARKET NEWS:
{market_news_text}

GLOBAL MARKET NEWS:
{global_news_text}

Provide analysis in this format:

MARKET MOOD: [Bullish/Bearish/Neutral] - one line summary

NIFTY OUTLOOK:
- Current trend
- Key level to watch

TOP OPPORTUNITIES TODAY:
1. [Stock] - [Reason] - [Action]
2. [Stock] - [Reason] - [Action]
3. [Stock] - [Reason] - [Action]

SECTORS TO WATCH:
- Bullish sector and why
- Bearish sector and why

RISK ALERTS:
- Major risks from news

OVERNIGHT GLOBAL IMPACT:
- How global news affects Indian market

SUGGESTED FOCUS FOR TODAY:
- One actionable suggestion

Keep concise and specific to Indian retail investor."""

    try:
        message = client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=1000,
            messages=[{"role": "user", "content": prompt}]
        )
        analysis = message.content[0].text

        output = {
            'timestamp': datetime.now().isoformat(),
            'analysis': analysis,
            'prices_snapshot': data.get('prices', {})
        }

        data_dir = Path(__file__).resolve().parent.parent.parent / 'data'
        with open(data_dir / 'latest_analysis.json', 'w', encoding='utf-8') as f:
            json.dump(output, f, indent=2, ensure_ascii=True)

        return analysis

    except Exception as e:
        print(f"ERROR Claude API: {e}")
        return None


if __name__ == "__main__":
    print("Trading Copilot - Basic Analyzer")
    print("=" * 50)
    analysis = analyze_market()
    if analysis:
        print("\n" + "=" * 50)
        print("MARKET ANALYSIS")
        print("=" * 50)
        print(analysis)
        print("=" * 50)
        print("Analysis saved to data/latest_analysis.json")