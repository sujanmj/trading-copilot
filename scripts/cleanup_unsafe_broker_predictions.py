#!/usr/bin/env python3
"""
Remove unsafe broker_predictions rows (dry-run by default).

Usage:
  python scripts/cleanup_unsafe_broker_predictions.py --dry-run
  python scripts/cleanup_unsafe_broker_predictions.py --write --reason "remove unsafe broker DB rows"
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


def _fail(msg: str) -> int:
    print(f'BROKER_PREDICTIONS_DB_CLEANUP_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description='Cleanup unsafe broker_predictions rows.')
    parser.add_argument('--dry-run', action='store_true', help='Preview removals only (default)')
    parser.add_argument('--write', action='store_true', help='Delete unsafe rows from broker_predictions')
    parser.add_argument('--reason', default='', help='Reason logged for cleanup run')
    args = parser.parse_args()

    dry_run = not args.write
    if args.dry_run:
        dry_run = True

    from backend.collectors.broker_db_audit import find_unsafe_broker_predictions
    from backend.storage.market_memory_db import delete_broker_predictions_by_ids

    unsafe = find_unsafe_broker_predictions()
    unsafe_rows = unsafe.get('unsafe_rows') or []
    unsafe_ids = [int(row['id']) for row in unsafe_rows if row.get('id') is not None]

    print(f'[BROKER_DB_CLEANUP] dry_run={dry_run}')
    if args.reason:
        print(f'[BROKER_DB_CLEANUP] reason={args.reason}')
    print(f'[BROKER_DB_CLEANUP] unsafe_found={len(unsafe_ids)}')

    for row in unsafe_rows:
        print(
            f"  REMOVE id={row.get('id')} | {row.get('ticker')} | "
            f"{row.get('broker_source')} | bucket={row.get('bucket')} | "
            f"reasons={row.get('reasons')} | {(row.get('title') or '')[:70]}"
        )

    removed = 0
    if not dry_run and unsafe_ids:
        removed = delete_broker_predictions_by_ids(unsafe_ids)

    print(f'[BROKER_DB_CLEANUP] removed={removed}')
    print('BROKER_PREDICTIONS_DB_CLEANUP_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
