#!/usr/bin/env python3
"""
CLI to resolve pending market memory outcomes.

Usage:
  python scripts/resolve_market_memory_outcomes.py --dry-run --limit 20
  python scripts/resolve_market_memory_outcomes.py --no-dry-run --write-pending --limit 20
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
    from backend.storage.market_memory_db import get_market_memory_stats, init_market_memory_db
    from backend.storage.market_memory_outcomes import (
        get_unresolved_predictions,
        resolve_pending_outcomes,
    )

    parser = argparse.ArgumentParser(description='Resolve canonical market memory outcomes')
    parser.set_defaults(dry_run=True)
    parser.add_argument(
        '--dry-run',
        dest='dry_run',
        action='store_true',
        help='Do not write outcomes (default)',
    )
    parser.add_argument(
        '--no-dry-run',
        dest='dry_run',
        action='store_false',
        help='Allow writes when combined with --write-pending',
    )
    parser.add_argument(
        '--write-pending',
        action='store_true',
        help='Write PENDING/manual outcomes for unresolved predictions',
    )
    parser.add_argument('--limit', type=int, default=100, help='Max predictions to examine')
    args = parser.parse_args()

    if not init_market_memory_db():
        print('[RESOLVE] init_market_memory_db failed', file=sys.stderr)
        return 1

    stats = get_market_memory_stats()
    print('[RESOLVE] stats_before=' + json.dumps(stats, default=str))

    prediction_count = int(stats.get('predictions') or 0)
    unresolved = get_unresolved_predictions(limit=args.limit)
    print(f'[RESOLVE] unresolved_predictions={len(unresolved)}')

    if prediction_count == 0:
        print('[RESOLVE] predictions=0; exiting cleanly')
        return 0

    summary = resolve_pending_outcomes(
        limit=args.limit,
        dry_run=args.dry_run,
        write_pending=args.write_pending,
    )
    print('[RESOLVE] summary=' + json.dumps(summary, default=str))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
