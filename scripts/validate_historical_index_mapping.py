#!/usr/bin/env python3
"""
Validate historical index symbol mapping for Yahoo/yfinance fetch.

Usage:
  python scripts/validate_historical_index_mapping.py

Prints exactly HISTORICAL_INDEX_MAPPING_OK on success; exits 1 on failure.
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
    print(f'HISTORICAL_INDEX_MAPPING_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.analytics.historical_symbol_mapping import resolve_yfinance_symbol

    import import_historical_prices as ihp

    expected = {
        'NIFTY 50': '^NSEI',
        'SENSEX': '^BSESN',
        'BANKNIFTY': '^NSEBANK',
    }
    for canonical, symbol in expected.items():
        mapped = resolve_yfinance_symbol(canonical, 'INDIA')
        if mapped != symbol:
            return _fail(f'{canonical!r} -> {mapped!r}, expected {symbol!r}')
        helper = ihp._yfinance_symbol(canonical, 'INDIA')
        if helper != symbol:
            return _fail(f'import helper {canonical!r} -> {helper!r}, expected {symbol!r}')
        if symbol.endswith('.NS'):
            return _fail(f'mapped index symbol must not use .NS: {symbol!r}')

    print('HISTORICAL_INDEX_MAPPING_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
