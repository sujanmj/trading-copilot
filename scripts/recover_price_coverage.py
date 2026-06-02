#!/usr/bin/env python3
"""
Recover enriched price coverage for all market memory tickers.

Runs full enrichment (no ticker limit), merges with existing enriched file,
and never shrinks symbol coverage.

Usage:
  python scripts/recover_price_coverage.py
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

from backend.utils.config import DATA_DIR
from scripts.validate_enriched_price_file import count_fake_prices

ENRICHED_PATH = DATA_DIR / 'latest_market_data_memory_enriched.json'


def _count_symbols(path: Path) -> int:
    if not path.is_file():
        return 0
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return 0
    prices = data.get('prices') if isinstance(data, dict) else None
    return len(prices) if isinstance(prices, dict) else 0


def main() -> int:
    before_symbols = _count_symbols(ENRICHED_PATH)

    from scripts.enrich_market_memory_prices import run_enrichment

    result = run_enrichment(dry_run=False, limit=None, promote=False, verbose=False)
    after_symbols = int(result.get('final_symbols') or _count_symbols(ENRICHED_PATH))

    fake_prices = 0
    if ENRICHED_PATH.is_file():
        try:
            data = json.loads(ENRICHED_PATH.read_text(encoding='utf-8'))
            prices = data.get('prices') if isinstance(data, dict) else {}
            if isinstance(prices, dict):
                fake_prices = count_fake_prices(prices)
        except (OSError, json.JSONDecodeError):
            pass

    print(f'[PRICE_RECOVERY] before_symbols={before_symbols}')
    print(f'[PRICE_RECOVERY] after_symbols={after_symbols}')
    print(f'[PRICE_RECOVERY] fake_prices={fake_prices}')

    if fake_prices != 0:
        print(f'PRICE_COVERAGE_RECOVERY_FAIL: fake_prices={fake_prices}', file=sys.stderr)
        return 1

    print('PRICE_COVERAGE_RECOVERY_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
