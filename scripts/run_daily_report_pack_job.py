#!/usr/bin/env python3
"""
Run daily report pack scheduler job (local-only).

Usage:
  python scripts/run_daily_report_pack_job.py --mode auto
  python scripts/run_daily_report_pack_job.py --mode research --dry-run
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if str(Path.cwd().resolve()) != str(PROJECT_ROOT.resolve()):
    os.chdir(PROJECT_ROOT)


def _apply_local_defaults() -> None:
    for key, val in {
        'LOCAL_DEV_MODE': '1',
        'LOCAL_ONLY': '1',
        'DISABLE_TELEGRAM': '1',
        'DISABLE_TELEGRAM_LISTENER': '1',
        'DISABLE_TELEGRAM_SENDS': '1',
    }.items():
        os.environ.setdefault(key, val)


def _fail(msg: str) -> int:
    print(f'DAILY_REPORT_PACK_JOB_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description='Run daily report pack scheduler job.')
    parser.add_argument('--mode', choices=('auto', 'premarket', 'postmarket', 'research'), default='auto')
    parser.add_argument('--dry-run', action='store_true', help='Route only; write no files')
    parser.add_argument('--limit', type=int, default=25)
    args = parser.parse_args()

    _apply_local_defaults()

    from backend.scheduler.daily_report_pack_job import run_daily_report_pack_job

    result = run_daily_report_pack_job(args.mode, dry_run=args.dry_run, limit=args.limit)
    if result.get('ok') is not True:
        return _fail((result.get('warnings') or ['job refused'])[0])

    print(f'[DAILY_PACK_JOB] mode={result.get("mode")}')
    print(f'[DAILY_PACK_JOB] market_mode={result.get("market_mode")}')
    print(f'[DAILY_PACK_JOB] generated={result.get("generated")}')
    latest = (result.get('files') or {}).get('latest', 'data/daily_report_pack_latest.json')
    print(f'[DAILY_PACK_JOB] output={latest}')
    for warning in result.get('warnings') or []:
        print(f'[DAILY_PACK_JOB] warning={warning}')
    print('DAILY_REPORT_PACK_JOB_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
