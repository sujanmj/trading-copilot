#!/usr/bin/env python3
"""
Validate data/latest_market_data_memory_enriched.json shape and safety.

Usage:
  python scripts/validate_enriched_price_file.py

Prints exactly ENRICHED_PRICE_FILE_OK on success; exits 1 on failure.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if str(Path.cwd().resolve()) != str(PROJECT_ROOT.resolve()):
    import os

    os.chdir(PROJECT_ROOT)

from backend.utils.config import DATA_DIR

ENRICHED_PATH = DATA_DIR / 'latest_market_data_memory_enriched.json'
FAKE_SOURCE_MARKERS = ('fake', 'mock', 'placeholder', 'dummy', 'test_price')


def _fail(msg: str) -> int:
    print(f'ENRICHED_PRICE_FILE_FAIL: {msg}', file=sys.stderr)
    return 1


def _to_float(value: Any) -> float | None:
    if value is None or str(value).strip() == '':
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _extract_price(entry: Any) -> float | None:
    if isinstance(entry, (int, float)) and not isinstance(entry, bool):
        return float(entry)
    if isinstance(entry, dict):
        for field in ('price', 'last_price', 'ltp', 'close'):
            val = _to_float(entry.get(field))
            if val is not None:
                return val
    return _to_float(entry)


def count_fake_prices(prices: dict[str, Any]) -> int:
    fake_count = 0
    for symbol, entry in prices.items():
        price = _extract_price(entry)
        source = ''
        if isinstance(entry, dict):
            source = str(entry.get('source') or '').lower()
        if price is None or price <= 0:
            fake_count += 1
            continue
        if any(marker in source for marker in FAKE_SOURCE_MARKERS):
            fake_count += 1
            continue
        if str(symbol).startswith('__TEST__'):
            fake_count += 1
    return fake_count


def build_sample(prices: dict[str, Any], *, limit: int = 5) -> list[str]:
    sample: list[str] = []
    for symbol in sorted(prices.keys()):
        entry = prices.get(symbol)
        price = _extract_price(entry)
        if price is None:
            sample.append(str(symbol))
        else:
            sample.append(f'{symbol}={price:.2f}')
        if len(sample) >= limit:
            break
    return sample


def main() -> int:
    exists = ENRICHED_PATH.is_file()
    print(f'[ENRICHED_PRICE_FILE] exists={exists}')

    if not exists:
        print('[ENRICHED_PRICE_FILE] symbols=0')
        print('[ENRICHED_PRICE_FILE] fake_prices=0')
        print('[ENRICHED_PRICE_FILE] sample=[]')
        return _fail(f'missing enriched price file: {ENRICHED_PATH}')

    try:
        data = json.loads(ENRICHED_PATH.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError) as exc:
        return _fail(f'invalid enriched price file: {exc}')

    if not isinstance(data, dict):
        return _fail('enriched price file root is not an object')

    prices = data.get('prices')
    if not isinstance(prices, dict):
        return _fail('enriched price file missing prices dict')

    symbol_count = len(prices)
    fake_prices = count_fake_prices(prices)
    sample = build_sample(prices)

    print(f'[ENRICHED_PRICE_FILE] symbols={symbol_count}')
    print(f'[ENRICHED_PRICE_FILE] fake_prices={fake_prices}')
    print(f'[ENRICHED_PRICE_FILE] sample={sample}')

    if fake_prices != 0:
        return _fail(f'expected fake_prices=0, got {fake_prices}')

    if symbol_count <= 15:
        return _fail(f'expected enriched symbols > 15, got {symbol_count}')

    print('ENRICHED_PRICE_FILE_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
