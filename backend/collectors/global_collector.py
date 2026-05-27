"""
Global markets collector — US, Asia, macro, crypto, futures for 24/7 intelligence.
"""

from __future__ import annotations

import json
import logging
import warnings
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import yfinance as yf

from backend.storage.json_io import atomic_write_json
from backend.utils.config import DATA_DIR
from backend.utils.market_data_validator import load_previous_snapshot, validate_market_snapshot
from backend.utils.market_hours import get_market_period

logging.getLogger('yfinance').setLevel(logging.CRITICAL)
warnings.filterwarnings('ignore', category=FutureWarning)

OUTPUT_FILE = DATA_DIR / 'global_markets.json'

TICKER_GROUPS = {
    'USA_INDICES': {
        'S&P_500': '^GSPC',
        'NASDAQ': '^IXIC',
        'DOW_JONES': '^DJI',
        'VIX': '^VIX',
        'US_FUTURES_NQ': 'NQ=F',
        'US_FUTURES_ES': 'ES=F',
    },
    'USA_RATES': {
        'US_10Y': '^TNX',
        'US_2Y': '^IRX',
    },
    'ASIA_INDICES': {
        'NIKKEI': '^N225',
        'HANG_SENG': '^HSI',
        'SHANGHAI': '000001.SS',
        'SGX_NIFTY': 'SGXNIFTY.NS',
    },
    'GLOBAL_MACRO': {
        'GOLD': 'GC=F',
        'SILVER': 'SI=F',
        'CRUDE_OIL': 'CL=F',
        'NAT_GAS': 'NG=F',
        'DXY': 'DX-Y.NYB',
        'BTC': 'BTC-USD',
        'ETH': 'ETH-USD',
    },
}

GEOPOLITICS_KEYWORDS = (
    'trump', 'fed', 'federal reserve', 'boj', 'bank of japan', 'china', 'pboc',
    'iran', 'russia', 'sanction', 'tariff', 'ceasefire', 'war', 'missile',
    'nato', 'opec', 'middle east', 'ukraine', 'taiwan', 'peace deal',
)

REGION_MAP = {
    'USA_INDICES': 'usa',
    'USA_RATES': 'usa',
    'ASIA_INDICES': 'asia',
    'GLOBAL_MACRO': 'global',
}


def _fetch_symbol(name: str, ticker: str) -> Optional[dict]:
    try:
        data = yf.download(ticker, period='5d', progress=False)
        if len(data) < 2:
            return None
        close_yesterday = float(data['Close'].iloc[-2].item())
        close_today = float(data['Close'].iloc[-1].item())
        if close_today != close_today or close_yesterday != close_yesterday:
            return None
        pct_change = ((close_today - close_yesterday) / close_yesterday) * 100
        return {
            'ticker': ticker,
            'price': round(close_today, 2),
            'change_percent': round(pct_change, 2),
            'change_pct': round(pct_change, 2),
            'latest_price': round(close_today, 2),
            'source': f'yfinance:{ticker}',
        }
    except Exception as exc:
        print(f"  [ERROR] {name.ljust(16)} -> {exc}")
        return None


def _mood_from_change(avg_change: float) -> str:
    if avg_change >= 0.35:
        return 'BULLISH'
    if avg_change <= -0.35:
        return 'BEARISH'
    return 'NEUTRAL'


def _scan_geopolitics() -> List[dict]:
    alerts: List[dict] = []
    sources = [
        DATA_DIR / 'news_feed.json',
        DATA_DIR / 'inshorts_feed.json',
        DATA_DIR / 'govt_intelligence.json',
    ]
    seen = set()
    for path in sources:
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding='utf-8'))
        except Exception:
            continue
        items = []
        if path.name == 'news_feed.json':
            items = payload.get('articles') or []
        elif path.name == 'inshorts_feed.json':
            items = payload.get('stories') or []
        elif path.name == 'govt_intelligence.json':
            items = (payload.get('alerts') or payload.get('items') or [])
        for item in items[:40]:
            if not isinstance(item, dict):
                continue
            text = ' '.join([
                str(item.get('title') or ''),
                str(item.get('summary') or item.get('headline') or ''),
                str(item.get('message') or ''),
            ]).lower()
            hits = [k for k in GEOPOLITICS_KEYWORDS if k in text]
            if not hits:
                continue
            key = text[:120]
            if key in seen:
                continue
            seen.add(key)
            alerts.append({
                'message': str(item.get('title') or item.get('headline') or item.get('message') or '')[:200],
                'keywords': hits[:5],
                'source': path.stem,
                'severity': 'HIGH' if any(k in text for k in ('war', 'sanction', 'tariff', 'missile', 'iran')) else 'MEDIUM',
            })
            if len(alerts) >= 12:
                break
    return alerts


def _build_sentiment(grouped_markets: dict) -> dict:
    sentiment = {}
    region_changes: Dict[str, List[float]] = {'usa': [], 'asia': [], 'global': [], 'europe': []}
    for group, symbols in grouped_markets.items():
        region = REGION_MAP.get(group, 'global')
        for row in symbols.values():
            ch = row.get('change_percent')
            if ch is not None:
                region_changes.setdefault(region, []).append(float(ch))
    for region, changes in region_changes.items():
        if not changes:
            continue
        avg = sum(changes) / len(changes)
        sentiment[region] = {
            'mood': _mood_from_change(avg),
            'average_change': round(avg, 2),
            'expected_open': round(avg * 0.65, 2),
            'sample_size': len(changes),
        }
    return sentiment


def fetch_global_sentiment():
    period = get_market_period()
    print('=' * 60)
    print(f'GLOBAL MARKETS COLLECTOR v3 | period={period}')
    print('=' * 60)

    grouped: Dict[str, dict] = {}
    flat: Dict[str, dict] = {}
    for group, symbols in TICKER_GROUPS.items():
        grouped[group] = {}
        for name, ticker in symbols.items():
            row = _fetch_symbol(name, ticker)
            if not row:
                print(f'  [FAIL] {name.ljust(16)} -> insufficient data')
                continue
            grouped[group][name] = row
            flat[name] = row
            print(f"  [OK] {name.ljust(16)} -> {row['change_percent']:+.2f}%")

    sentiment = _build_sentiment(grouped)
    geopolitics = _scan_geopolitics()

    prev = load_previous_snapshot(OUTPUT_FILE)
    prev_prices = {}
    for name in flat:
        prev_row = (prev.get('markets') or {}).get(name) or {}
        if isinstance(prev_row, dict):
            prev_prices[name] = {
                'price': prev_row.get('latest_price') or prev_row.get('price'),
                'change_percent': prev_row.get('change_pct') or prev_row.get('change_percent'),
                'source': 'previous',
            }
    validated, _ = validate_market_snapshot(
        {'prices': {k: {'price': v['price'], 'change_percent': v['change_percent'], 'source': v['source']} for k, v in flat.items()},
         'last_updated': datetime.now(timezone.utc).isoformat(),
         'total_symbols': len(flat)},
        previous_snapshot={'prices': prev_prices},
        file_label='global',
    )

    for group in grouped:
        for name in list(grouped[group].keys()):
            vrow = (validated.get('prices') or {}).get(name)
            if vrow:
                grouped[group][name]['price'] = vrow.get('price')
                grouped[group][name]['change_percent'] = vrow.get('change_percent')
                grouped[group][name]['change_pct'] = vrow.get('change_percent')
                grouped[group][name]['latest_price'] = vrow.get('price')

    output = {
        'last_updated': datetime.now(timezone.utc).isoformat(),
        'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'market_period': period,
        'sentiment': sentiment,
        'markets': grouped,
        'flat_markets': flat,
        'geopolitics': geopolitics,
        'alerts': [
            {'message': a.get('message'), 'severity': a.get('severity'), 'keywords': a.get('keywords')}
            for a in geopolitics[:8]
        ],
        'validation': validated.get('validation'),
        'coverage': {
            'usa': len(grouped.get('USA_INDICES') or {}) + len(grouped.get('USA_RATES') or {}),
            'asia': len(grouped.get('ASIA_INDICES') or {}),
            'macro': len(grouped.get('GLOBAL_MACRO') or {}),
            'geopolitics_alerts': len(geopolitics),
        },
    }

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(OUTPUT_FILE, output)
    print('-' * 60)
    print(f'[SAVED] Global intelligence — {len(flat)} symbols, {len(geopolitics)} geo alerts')
    print('=' * 60)
    return output


if __name__ == '__main__':
    fetch_global_sentiment()
