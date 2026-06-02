#!/usr/bin/env python3
"""
Railway report bootstrap — non-destructive generate of cached decision reports (Stage 46F).

Usage:
  python scripts/railway_bootstrap_reports.py
  python scripts/railway_bootstrap_reports.py --force --limit 25

Uses RAILWAY_DATA_DIR or /app/data via get_data_path().
Never deletes memory DB or resets predictions.

Prints RAILWAY_BOOTSTRAP_REPORTS_OK on success.
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


def _fail(msg: str) -> int:
    print(f'RAILWAY_BOOTSTRAP_REPORTS_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description='Bootstrap Railway cached reports.')
    parser.add_argument('--force', action='store_true', help='Regenerate even if cache is fresh')
    parser.add_argument('--limit', type=int, default=25, help='Candidate limit for reports')
    parser.add_argument('--timeout', type=float, default=120, help='Bootstrap timeout seconds')
    args = parser.parse_args()

    from backend.storage.data_paths import get_data_root, log_data_startup
    from backend.analytics.railway_decision_bootstrap import (
        report_cache_needs_bootstrap,
        run_railway_bootstrap_reports,
    )

    log_data_startup()
    data_root = get_data_root()
    print('RAILWAY_STAGE_46F_LIVE_DATA_BOOTSTRAP', flush=True)
    print(f'[RAILWAY_BOOTSTRAP_REPORTS] data_root={data_root}', flush=True)

    if not args.force and not report_cache_needs_bootstrap():
        print('[RAILWAY_BOOTSTRAP_REPORTS] cache_fresh — skipped', flush=True)
        print('RAILWAY_BOOTSTRAP_REPORTS_OK')
        return 0

    result = run_railway_bootstrap_reports(
        timeout_sec=args.timeout,
        limit=args.limit,
        force=args.force,
        railway_only=False,
    )
    if result.get('skipped'):
        print('[RAILWAY_BOOTSTRAP_REPORTS] skipped', flush=True)
        print('RAILWAY_BOOTSTRAP_REPORTS_OK')
        return 0

    steps = result.get('steps') or {}
    for key, status in steps.items():
        print(f'[RAILWAY_BOOTSTRAP_REPORTS] {key}={status}', flush=True)

    if result.get('warming'):
        return _fail(result.get('message') or 'bootstrap warming — try again shortly')

    if result.get('ok') is not True:
        return _fail('one or more bootstrap steps failed')

    print('RAILWAY_BOOTSTRAP_REPORTS_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
