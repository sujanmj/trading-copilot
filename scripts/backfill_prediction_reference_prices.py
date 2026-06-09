#!/usr/bin/env python3
"""
Safe reference-price backfill for pending predictions — Stage 49C.

Default dry-run. Use --apply to write real stored prices only.

Usage:
  python scripts/backfill_prediction_reference_prices.py
  python scripts/backfill_prediction_reference_prices.py --apply
  python scripts/backfill_prediction_reference_prices.py --apply --force
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if str(Path.cwd().resolve()) != str(PROJECT_ROOT.resolve()):
    import os

    os.chdir(PROJECT_ROOT)


def main() -> int:
    parser = argparse.ArgumentParser(description='Backfill missing prediction reference prices from stored data.')
    parser.add_argument('--apply', action='store_true', help='Write changes (default is dry-run).')
    parser.add_argument('--force', action='store_true', help='Overwrite existing reference_price values.')
    parser.add_argument('--limit', type=int, default=500)
    args = parser.parse_args()

    from backend.storage.outcome_price_lookup import backfill_prediction_reference_prices

    dry_run = not args.apply
    summary = backfill_prediction_reference_prices(dry_run=dry_run, force=args.force, limit=max(1, args.limit))
    print('REFERENCE_PRICE_BACKFILL_OK', flush=True)
    print(f"dry_run={'true' if dry_run else 'false'}", flush=True)
    print(f"candidates={int(summary.get('candidates') or 0)}", flush=True)
    print(f"updated={int(summary.get('updated') or 0)}", flush=True)
    print(f"skipped_no_price={int(summary.get('skipped_no_price') or 0)}", flush=True)
    print(f"errors={int(summary.get('errors') or 0)}", flush=True)
    return 0 if int(summary.get('errors') or 0) == 0 else 1


if __name__ == '__main__':
    raise SystemExit(main())
