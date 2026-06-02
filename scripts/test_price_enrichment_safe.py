#!/usr/bin/env python3
"""
Safety tests for scripts/enrich_market_memory_prices.py (dry-run only).

Usage:
  python scripts/test_price_enrichment_safe.py

Prints exactly PRICE_ENRICHMENT_SAFE_OK on success; exits 1 on failure.
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


def _fail(msg: str) -> int:
    print(f'PRICE_ENRICHMENT_SAFE_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    try:
        import scripts.enrich_market_memory_prices as enrich
    except Exception as exc:
        return _fail(f'import enrich_market_memory_prices failed: {exc}')

    from backend.storage.market_memory_db import get_market_memory_stats

    stats_before = get_market_memory_stats()
    preds_before = int(stats_before.get('predictions') or 0)
    outcomes_before = int(stats_before.get('outcomes') or 0)

    result = enrich.run_enrichment(dry_run=True, limit=10, verbose=False)
    if not isinstance(result, dict):
        return _fail('run_enrichment did not return a dict')

    if result.get('fake_prices') != 0:
        return _fail(f'expected fake_prices=0, got {result.get("fake_prices")}')

    if not result.get('dry_run'):
        return _fail('run_enrichment must stay in dry_run mode for safety test')

    stats_after = get_market_memory_stats()
    preds_after = int(stats_after.get('predictions') or 0)
    outcomes_after = int(stats_after.get('outcomes') or 0)

    if preds_before != preds_after:
        return _fail(
            f'dry-run changed prediction count: {preds_before} -> {preds_after}',
        )
    if outcomes_before != outcomes_after:
        return _fail(
            f'dry-run changed outcome count: {outcomes_before} -> {outcomes_after}',
        )

    print('PRICE_ENRICHMENT_SAFE_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
