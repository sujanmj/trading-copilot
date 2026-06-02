#!/usr/bin/env python3
"""
Build company alias map from historical ticker universe, enriched prices, and common aliases.

Output: data/company_alias_map.json
Prints COMPANY_ALIAS_MAP_OK on success.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if str(Path.cwd().resolve()) != str(PROJECT_ROOT.resolve()):
    import os

    os.chdir(PROJECT_ROOT)

from backend.utils.config import DATA_DIR

OUTPUT_PATH = DATA_DIR / 'company_alias_map.json'
UNIVERSE_PATH = DATA_DIR / 'historical_ticker_universe.json'
ENRICHED_PATH = DATA_DIR / 'latest_market_data_memory_enriched.json'
MARKET_PATH = DATA_DIR / 'latest_market_data.json'

COMMON_ALIASES: dict[str, str] = {
    'reliance': 'RELIANCE',
    'reliance industries': 'RELIANCE',
    'suzlon': 'SUZLON',
    'nmdc': 'NMDC',
    'tata tech': 'TATATECH',
    'tata technologies': 'TATATECH',
    'pb fintech': 'POLICYBZR',
    'policybazaar': 'POLICYBZR',
    'pnc infratech': 'PNCINFRA',
    'mcx': 'MCX',
    'wockhardt': 'WOCKPHARMA',
    'icici bank': 'ICICIBANK',
    'au small finance bank': 'AUBANK',
    'tata consultancy': 'TCS',
    'tcs': 'TCS',
    'infosys': 'INFY',
    'wipro': 'WIPRO',
    'hdfc bank': 'HDFCBANK',
    'tata motors': 'TATAMOTORS',
    'tata steel': 'TATASTEEL',
    'tata power': 'TATAPOWER',
    'sun pharma': 'SUNPHARMA',
    'asian paints': 'ASIANPAINT',
    'bajaj finance': 'BAJFINANCE',
    'maruti suzuki': 'MARUTI',
    'bharti airtel': 'BHARTIARTL',
    'adani enterprises': 'ADANIENT',
    'jio financial': 'JIOFIN',
    'cummins india': 'CUMMINSIND',
    'ola electric': 'OLAELEC',
}


def _fail(msg: str) -> int:
    print(f'COMPANY_ALIAS_MAP_FAIL: {msg}', file=sys.stderr)
    return 1


def _normalize_ticker(ticker: str) -> str:
    raw = re.sub(r'\s+', ' ', str(ticker or '').strip().upper())
    return raw.replace(' ', '')


def _tickers_from_universe() -> set[str]:
    tickers: set[str] = set()
    if UNIVERSE_PATH.is_file():
        try:
            data = json.loads(UNIVERSE_PATH.read_text(encoding='utf-8'))
            for row in data.get('tickers') or []:
                if isinstance(row, dict):
                    token = _normalize_ticker(str(row.get('ticker') or ''))
                else:
                    token = _normalize_ticker(str(row))
                if len(token) >= 2:
                    tickers.add(token)
        except (OSError, json.JSONDecodeError):
            pass

    for path in (ENRICHED_PATH, MARKET_PATH):
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError):
            continue
        prices = data.get('prices') or data.get('symbols') or {}
        if isinstance(prices, dict):
            for key in prices:
                token = _normalize_ticker(str(key))
                if len(token) >= 2:
                    tickers.add(token)
    return tickers


def _alias_from_ticker(ticker: str) -> str | None:
    """Generate a readable alias from ticker token when unambiguous."""
    token = _normalize_ticker(ticker)
    if len(token) < 4 or not token.isalpha():
        return None
    return None


def main() -> int:
    tickers = _tickers_from_universe()
    if not tickers:
        return _fail('no tickers found in universe or enriched prices')

    aliases: dict[str, str] = {}
    for alias, ticker in COMMON_ALIASES.items():
        canon = _normalize_ticker(ticker)
        if canon in tickers or canon:
            aliases[alias.lower().strip()] = canon

    for ticker in sorted(tickers):
        lowered = ticker.lower()
        if lowered not in aliases and len(ticker) >= 4:
            spaced = re.sub(r'([a-z])([A-Z])', r'\1 \2', ticker).lower()
            if spaced != lowered and spaced not in aliases:
                aliases.setdefault(spaced, ticker)

    payload = {
        'generated_at': datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        'ticker_count': len(tickers),
        'alias_count': len(aliases),
        'aliases': dict(sorted(aliases.items())),
        'tickers': sorted(tickers),
    }

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding='utf-8')
    print(f'[COMPANY_ALIAS_MAP] tickers={len(tickers)} aliases={len(aliases)}')
    print('COMPANY_ALIAS_MAP_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
