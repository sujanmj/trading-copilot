#!/usr/bin/env python3
"""
Replay canonical prediction outcomes using historical OHLCV prices.

Usage:
  python scripts/replay_prediction_outcomes_historical.py --from 2026-05-01 --to 2026-05-30
  python scripts/replay_prediction_outcomes_historical.py --from 2026-05-01 --to 2026-05-30 --dry-run

Prints exactly HISTORICAL_REPLAY_OK on success; exits 1 on failure.
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
    print(f'HISTORICAL_REPLAY_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description='Replay prediction outcomes from historical prices.')
    parser.add_argument('--from', dest='from_date', help='Filter predictions from date YYYY-MM-DD')
    parser.add_argument('--to', dest='to_date', help='Filter predictions to date YYYY-MM-DD')
    parser.add_argument('--market', choices=('INDIA', 'USA'), default=None)
    parser.add_argument('--limit', type=int, default=None)
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--verbose', action='store_true')
    args = parser.parse_args()

    from backend.storage.historical_outcome_replay import replay_prediction_outcomes
    from backend.storage.market_memory_db import get_market_memory_stats

    stats_before = get_market_memory_stats()
    preds_before = int(stats_before.get('predictions') or 0)

    summary = replay_prediction_outcomes(
        from_date=args.from_date,
        to_date=args.to_date,
        market=args.market,
        limit=args.limit,
        dry_run=args.dry_run,
        verbose=args.verbose,
    )

    print(f'[HISTORICAL_REPLAY] dry_run={summary.get("dry_run")}')
    print(f'[HISTORICAL_REPLAY] predictions_checked={summary.get("predictions_checked", 0)}')
    print(f'[HISTORICAL_REPLAY] resolved={summary.get("resolved", 0)}')
    print(f'[HISTORICAL_REPLAY] written={summary.get("written", 0)}')
    print(f'[HISTORICAL_REPLAY] skipped={summary.get("skipped", 0)}')
    print(f'[HISTORICAL_REPLAY] wins={summary.get("wins", 0)}')
    print(f'[HISTORICAL_REPLAY] losses={summary.get("losses", 0)}')
    print(f'[HISTORICAL_REPLAY] ambiguous={summary.get("ambiguous", 0)}')
    print(f'[HISTORICAL_REPLAY] unresolved={summary.get("unresolved", 0)}')
    print(f'[HISTORICAL_REPLAY] errors={summary.get("errors", 0)}')

    stats_after = get_market_memory_stats()
    preds_after = int(stats_after.get('predictions') or 0)
    if preds_before != preds_after:
        return _fail(f'canonical prediction count changed {preds_before} -> {preds_after}')

    if summary.get('errors', 0) > 0 and not args.dry_run:
        return _fail('replay errors > 0')

    print('HISTORICAL_REPLAY_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
