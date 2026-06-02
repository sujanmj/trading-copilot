"""
Map canonical historical tickers to Yahoo/yfinance fetch symbols.

DB rows keep canonical names (e.g. NIFTY 50); fetch uses mapped symbols (e.g. ^NSEI).
"""

from __future__ import annotations

INDEX_YFINANCE_SYMBOLS: dict[str, str] = {
    'NIFTY 50': '^NSEI',
    'NIFTY': '^NSEI',
    'NIFTY50': '^NSEI',
    'SENSEX': '^BSESN',
    'BSE SENSEX': '^BSESN',
    'BANKNIFTY': '^NSEBANK',
    'NIFTY BANK': '^NSEBANK',
}


def normalize_historical_ticker(ticker: str) -> str:
    raw = str(ticker or '').strip().upper()
    if raw.startswith('NSE:'):
        raw = raw[4:]
    if raw.endswith('-EQ'):
        raw = raw[:-3]
    if raw.endswith('.NS') or raw.endswith('.BO'):
        raw = raw.rsplit('.', 1)[0]
    return raw


def is_index_ticker(ticker: str) -> bool:
    return normalize_historical_ticker(ticker) in INDEX_YFINANCE_SYMBOLS


def resolve_yfinance_symbol(ticker: str, market: str) -> str:
    clean = normalize_historical_ticker(ticker)
    market_upper = str(market or '').strip().upper()
    if market_upper == 'USA':
        return clean
    if clean.startswith('^'):
        return clean
    mapped = INDEX_YFINANCE_SYMBOLS.get(clean)
    if mapped:
        return mapped
    return f'{clean}.NS'
