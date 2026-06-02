#!/usr/bin/env python3
"""
Bulk replay canonical predictions against historical OHLCV prices.

Usage:
  python scripts/bulk_replay_historical_outcomes.py --dry-run
  python scripts/bulk_replay_historical_outcomes.py --write --from 2025-01-01 --to 2026-05-30
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if str(Path.cwd().resolve()) != str(PROJECT_ROOT.resolve()):
    import os

    os.chdir(PROJECT_ROOT)

from backend.utils.config import DATA_DIR

REPORT_PATH = DATA_DIR / 'historical_replay_report.json'


def _fail(msg: str) -> int:
    print(f'BULK_HISTORICAL_REPLAY_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description='Bulk replay prediction outcomes historically.')
    parser.add_argument('--from', dest='from_date', help='Filter predictions from YYYY-MM-DD')
    parser.add_argument('--to', dest='to_date', help='Filter predictions to YYYY-MM-DD')
    parser.add_argument('--limit', type=int, default=None)
    parser.add_argument('--dry-run', action='store_true', help='Do not write replays (default)')
    parser.add_argument('--write', action='store_true', help='Write replays to historical DB')
    parser.add_argument('--verbose', action='store_true')
    args = parser.parse_args()

    dry_run = not args.write
    if args.dry_run:
        dry_run = True

    from backend.storage.historical_outcome_replay import replay_prediction_outcomes
    from backend.storage.market_memory_db import get_market_memory_stats

    stats_before = get_market_memory_stats()
    preds_before = int(stats_before.get('predictions') or 0)

    summary = replay_prediction_outcomes(
        from_date=args.from_date,
        to_date=args.to_date,
        limit=args.limit,
        dry_run=dry_run,
        verbose=args.verbose,
    )

    checked = int(summary.get('predictions_checked') or 0)
    replayed = int(summary.get('resolved') or 0)
    wins = int(summary.get('wins') or 0)
    losses = int(summary.get('losses') or 0)
    ambiguous = int(summary.get('ambiguous') or 0)
    written = int(summary.get('written') or 0)

    print(f'[BULK_HIST_REPLAY] checked={checked}')
    print(f'[BULK_HIST_REPLAY] replayed={replayed}')
    print(f'[BULK_HIST_REPLAY] wins={wins}')
    print(f'[BULK_HIST_REPLAY] losses={losses}')
    print(f'[BULK_HIST_REPLAY] ambiguous={ambiguous}')
    print(f'[BULK_HIST_REPLAY] written={written}')

    stats_after = get_market_memory_stats()
    preds_after = int(stats_after.get('predictions') or 0)
    if preds_before != preds_after:
        return _fail(f'canonical prediction count changed {preds_before} -> {preds_after}')

    report: dict[str, Any] = {
        'generated_at': datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        'dry_run': dry_run,
        'from_date': args.from_date,
        'to_date': args.to_date,
        'checked': checked,
        'replayed': replayed,
        'wins': wins,
        'losses': losses,
        'ambiguous': ambiguous,
        'written': written,
        'skipped': int(summary.get('skipped') or 0),
        'unresolved': int(summary.get('unresolved') or 0),
        'errors': int(summary.get('errors') or 0),
    }
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')

    if summary.get('errors', 0) > 0 and not dry_run:
        return _fail('replay errors > 0')

    anomaly_excluded = int(summary.get('anomaly_excluded_dates') or 0)
    anomaly_warnings = int(summary.get('anomaly_warnings') or 0)
    if anomaly_excluded > 0:
        print(f'[BULK_HIST_REPLAY] anomaly_excluded_dates={anomaly_excluded}')
    if anomaly_warnings > 0:
        print(f'[BULK_HIST_REPLAY] anomaly_warnings={anomaly_warnings}')

    print('BULK_HISTORICAL_REPLAY_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
