#!/usr/bin/env python3
"""
Collect real broker/app stock picks from public RSS feeds into broker_prediction_inbox.json.

Usage:
  python scripts/collect_broker_predictions.py
  python scripts/collect_broker_predictions.py --dry-run --verbose
  python scripts/collect_broker_predictions.py --import --update-existing
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if str(Path.cwd().resolve()) != str(PROJECT_ROOT.resolve()):
    import os

    os.chdir(PROJECT_ROOT)


def _fail(msg: str) -> int:
    print(f'BROKER_APP_COLLECT_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description='Collect broker/app picks from public RSS feeds.')
    parser.add_argument('--dry-run', action='store_true', help='Collect without writing inbox JSON')
    parser.add_argument('--verbose', action='store_true', help='Verbose feed logging')
    parser.add_argument('--hours-back', type=int, default=72, help='RSS lookback window in hours')
    parser.add_argument('--feed-limit', type=int, default=25, help='Max entries per feed')
    parser.add_argument('--import', dest='do_import', action='store_true', help='Import inbox after collect')
    parser.add_argument('--update-existing', action='store_true', help='Pass --update-existing to import script')
    args = parser.parse_args()

    from backend.collectors.broker_app_collector import OUTPUT_FILE, collect_broker_app_predictions

    print('[BROKER_COLLECT] started')
    print(f'[BROKER_COLLECT] dry_run={args.dry_run} hours_back={args.hours_back}')

    result = collect_broker_app_predictions(
        dry_run=args.dry_run,
        hours_back=args.hours_back,
        feed_limit=args.feed_limit,
        verbose=args.verbose,
    )

    summary = result.get('summary') or {}
    print(f"[BROKER_COLLECT] feeds_ok={summary.get('feeds_ok', 0)} feeds_failed={summary.get('feeds_failed', 0)}")
    print(f"[BROKER_COLLECT] articles_seen={summary.get('articles_seen', 0)} pick_headlines={summary.get('pick_headlines', 0)}")
    print(f"[BROKER_COLLECT] accepted={summary.get('accepted', 0)} rejected_outcomes={summary.get('rejected_outcomes', 0)}")
    print(f"[BROKER_COLLECT] skipped_no_ticker={summary.get('skipped_no_ticker', 0)}")
    if not args.dry_run:
        print(f'[BROKER_COLLECT] wrote={OUTPUT_FILE}')
    else:
        print('[BROKER_COLLECT] dry_run_no_write=True')

    warnings = result.get('warnings') or []
    if warnings:
        print(f'[BROKER_COLLECT] warnings={len(warnings)}')

    if args.do_import and not args.dry_run:
        import_cmd = [
            sys.executable,
            str(PROJECT_ROOT / 'scripts' / 'import_broker_predictions.py'),
            '--file',
            str(OUTPUT_FILE),
        ]
        if args.update_existing:
            import_cmd.append('--update-existing')
        proc = subprocess.run(import_cmd, cwd=str(PROJECT_ROOT))
        if proc.returncode != 0:
            return _fail('import_broker_predictions failed')

    print('BROKER_APP_COLLECT_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
