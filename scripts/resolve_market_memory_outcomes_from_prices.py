#!/usr/bin/env python3
"""
Resolve market memory outcomes from a market price JSON file.

Usage:
  python scripts/resolve_market_memory_outcomes_from_prices.py --dry-run --limit 50
  python scripts/resolve_market_memory_outcomes_from_prices.py --limit 500
  python scripts/resolve_market_memory_outcomes_from_prices.py --price-file data/latest_market_data_memory_enriched.json --dry-run
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if str(Path.cwd().resolve()) != str(PROJECT_ROOT.resolve()):
    import os

    os.chdir(PROJECT_ROOT)


def main() -> int:
    from backend.storage.market_memory_db import init_market_memory_db
    from backend.storage.market_memory_outcomes import (
        DEFAULT_PRICE_HOLDING_PERIOD,
        LATEST_MARKET_DATA_PATH,
        resolve_outcomes_from_prices,
    )

    parser = argparse.ArgumentParser(
        description='Resolve canonical market memory outcomes from latest_market_data prices',
    )
    parser.add_argument(
        '--price-file',
        default=str(LATEST_MARKET_DATA_PATH),
        help='Market price JSON to resolve from (default: data/latest_market_data.json)',
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Do not write outcomes (default: writes when price evidence exists)',
    )
    parser.add_argument('--limit', type=int, default=100, help='Max predictions to examine')
    parser.add_argument('--verbose', action='store_true', help='Print per-prediction resolution details')
    parser.add_argument(
        '--allow-stale',
        action='store_true',
        help='Allow resolution even when latest_market_data is stale (default: reject stale)',
    )
    parser.add_argument(
        '--max-age-hours',
        type=float,
        default=24.0,
        help='Reject latest_market_data older than this many hours unless --allow-stale',
    )
    parser.add_argument(
        '--holding-period',
        default=DEFAULT_PRICE_HOLDING_PERIOD,
        help=f'Holding period for outcomes (default: {DEFAULT_PRICE_HOLDING_PERIOD})',
    )
    parser.add_argument(
        '--allow-suspicious',
        action='store_true',
        help='Allow resolution when price sanity gates fail (default: skip)',
    )
    parser.add_argument(
        '--max-latest-vs-entry-pct',
        type=float,
        default=20.0,
        help='Reject when |latest vs entry| exceeds this pct (default: 20)',
    )
    parser.add_argument(
        '--max-target-vs-entry-pct',
        type=float,
        default=30.0,
        help='Reject when |target vs entry| exceeds this pct (default: 30)',
    )
    parser.add_argument(
        '--max-stop-vs-entry-pct',
        type=float,
        default=30.0,
        help='Reject when |stop vs entry| exceeds this pct (default: 30)',
    )
    args = parser.parse_args()

    if not init_market_memory_db():
        print('[PRICE_OUTCOMES] init_market_memory_db failed', file=sys.stderr)
        return 1

    price_file = Path(args.price_file)
    print(f'[PRICE_OUTCOMES] price_file={price_file}')

    summary = resolve_outcomes_from_prices(
        limit=args.limit,
        dry_run=args.dry_run,
        holding_period=args.holding_period,
        verbose=args.verbose,
        market_data_path=price_file,
        allow_stale=args.allow_stale,
        max_age_hours=args.max_age_hours,
        allow_suspicious=args.allow_suspicious,
        max_latest_vs_entry_pct=args.max_latest_vs_entry_pct,
        max_target_vs_entry_pct=args.max_target_vs_entry_pct,
        max_stop_vs_entry_pct=args.max_stop_vs_entry_pct,
    )

    age = summary.get('latest_market_data_age_hours')
    print(f'[PRICE_OUTCOMES] latest_market_data_age_hours={age}')
    print(f'[PRICE_OUTCOMES] predictions_checked={summary.get("predictions_checked", 0)}')
    print(f'[PRICE_OUTCOMES] resolved={summary.get("resolved", 0)}')
    print(f'[PRICE_OUTCOMES] skipped={summary.get("skipped", 0)}')
    print(f'[PRICE_OUTCOMES] written={summary.get("written", 0)}')
    print(f'[PRICE_OUTCOMES] dry_run={summary.get("dry_run", False)}')
    print('[PRICE_OUTCOMES] stats=' + json.dumps(summary, default=str))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
