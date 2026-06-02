#!/usr/bin/env python3
"""
Unit tests for historical index symbol mapping (no network).

Usage:
  python scripts/test_historical_index_mapping.py

Prints exactly HISTORICAL_INDEX_MAPPING_TEST_OK on success; exits 1 on failure.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if str(Path.cwd().resolve()) != str(PROJECT_ROOT.resolve()):
    import os

    os.chdir(PROJECT_ROOT)

SCRIPTS_DIR = PROJECT_ROOT / 'scripts'
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


def _fail(msg: str) -> int:
    print(f'HISTORICAL_INDEX_MAPPING_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.analytics.historical_symbol_mapping import (
        INDEX_YFINANCE_SYMBOLS,
        is_index_ticker,
        normalize_historical_ticker,
        resolve_yfinance_symbol,
    )

    cases = {
        'NIFTY 50': '^NSEI',
        'NIFTY': '^NSEI',
        'NIFTY50': '^NSEI',
        'SENSEX': '^BSESN',
        'BSE SENSEX': '^BSESN',
        'BANKNIFTY': '^NSEBANK',
        'NIFTY BANK': '^NSEBANK',
    }
    for canonical, expected in cases.items():
        if INDEX_YFINANCE_SYMBOLS.get(normalize_historical_ticker(canonical)) != expected:
            return _fail(f'mapping mismatch for {canonical!r}')
        if resolve_yfinance_symbol(canonical, 'INDIA') != expected:
            return _fail(f'resolve_yfinance_symbol mismatch for {canonical!r}')
        if not is_index_ticker(canonical):
            return _fail(f'is_index_ticker false for {canonical!r}')

    if resolve_yfinance_symbol('RELIANCE', 'INDIA') != 'RELIANCE.NS':
        return _fail('equity ticker should append .NS')

    if resolve_yfinance_symbol('AAPL', 'USA') != 'AAPL':
        return _fail('USA ticker should not append .NS')

    for canonical in cases:
        symbol = resolve_yfinance_symbol(canonical, 'INDIA')
        if symbol.endswith('.NS'):
            return _fail(f'index symbol must not use .NS: {canonical!r} -> {symbol!r}')

    import import_historical_prices as ihp

    if ihp._yfinance_symbol('NIFTY 50', 'INDIA') != '^NSEI':
        return _fail('import helper NIFTY 50 mapping failed')
    if ihp._yfinance_symbol('SENSEX', 'INDIA') != '^BSESN':
        return _fail('import helper SENSEX mapping failed')

    print('HISTORICAL_INDEX_MAPPING_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
