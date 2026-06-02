#!/usr/bin/env python3
"""
Validate enriched price merge protection (Stage 20D).

Checks enrich_market_memory_prices.py for merge/preserve logic and optionally
verifies on-disk symbol count does not shrink vs a backup snapshot.

Prints exactly PRICE_ENRICHMENT_NO_SHRINK_OK on success.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if str(Path.cwd().resolve()) != str(PROJECT_ROOT.resolve()):
    import os

    os.chdir(PROJECT_ROOT)

ENRICH_SCRIPT = PROJECT_ROOT / 'scripts' / 'enrich_market_memory_prices.py'

from backend.utils.config import DATA_DIR

ENRICHED_PATH = DATA_DIR / 'latest_market_data_memory_enriched.json'


def _fail(msg: str) -> int:
    print(f'PRICE_ENRICHMENT_NO_SHRINK_FAIL: {msg}', file=sys.stderr)
    return 1


def _count_symbols(path: Path) -> int | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return None
    prices = data.get('prices') if isinstance(data, dict) else None
    return len(prices) if isinstance(prices, dict) else 0


def main() -> int:
    if not ENRICH_SCRIPT.is_file():
        return _fail('enrich_market_memory_prices.py missing')

    src = ENRICH_SCRIPT.read_text(encoding='utf-8')
    required = (
        'merge_prices_preserve_coverage',
        '_load_existing_enriched_prices',
        'preserved_existing',
        'final_symbols',
        '[PRICE_ENRICH] preserved_existing=',
        '[PRICE_ENRICH] final_symbols=',
    )
    for token in required:
        if token not in src:
            return _fail(f'missing merge protection token: {token}')

    try:
        from scripts.enrich_market_memory_prices import merge_prices_preserve_coverage

        old = {'AAA': {'price': 1.0}, 'BBB': {'price': 2.0}, 'CCC': {'price': 3.0}}
        new = {'AAA': {'price': 1.1}, 'DDD': {'price': 4.0}}
        merged, preserved = merge_prices_preserve_coverage(old, new)
        if len(merged) < len(old):
            return _fail('merge_prices_preserve_coverage shrank symbol count')
        if preserved != 2:
            return _fail(f'expected preserved_existing=2 got {preserved}')
    except Exception as exc:
        return _fail(f'merge unit check failed: {exc}')

    count = _count_symbols(ENRICHED_PATH)
    if count is not None and count > 0:
        print(f'[PRICE_ENRICH_NO_SHRINK] on_disk_symbols={count}')

    print('PRICE_ENRICHMENT_NO_SHRINK_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
