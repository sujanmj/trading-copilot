#!/usr/bin/env python3
"""
Validate broker/app collector inbox shape and optional live collect dry-run.

Usage:
  python scripts/collect_broker_predictions.py --dry-run
  python scripts/validate_broker_app_collector.py

Prints exactly BROKER_APP_COLLECTOR_VALIDATE_OK on success.
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
    print(f'BROKER_APP_COLLECTOR_VALIDATE_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.analytics.broker_prediction_intelligence import prepare_broker_pick_for_import
    from backend.collectors.broker_app_collector import (
        OUTPUT_FILE,
        collect_broker_app_predictions,
        load_broker_inbox,
    )

    dry = collect_broker_app_predictions(dry_run=True, hours_back=24, feed_limit=5, verbose=False)
    if dry.get('ok') is not True:
        return _fail('dry-run collect returned ok != true')

    summary = dry.get('summary') or {}
    print(
        f"[BROKER_COLLECTOR_VALIDATE] dry_run feeds_ok={summary.get('feeds_ok', 0)} "
        f"feeds_failed={summary.get('feeds_failed', 0)} accepted={summary.get('accepted', 0)}"
    )

    inbox = load_broker_inbox()
    if inbox.get('ok') is False and OUTPUT_FILE.is_file() is False:
        print('[BROKER_COLLECTOR_VALIDATE] inbox=missing (ok for first run)')
        print('BROKER_APP_COLLECTOR_VALIDATE_OK')
        return 0

    if not OUTPUT_FILE.is_file():
        return _fail(f'missing inbox after prior runs: {OUTPUT_FILE}')

    items = inbox.get('items')
    if not isinstance(items, list):
        return _fail('inbox items must be a list')

    for index, item in enumerate(items[:20], start=1):
        if not isinstance(item, dict):
            return _fail(f'item {index} is not an object')
        prepared = prepare_broker_pick_for_import(item, source_hint=item.get('broker_source'))
        if prepared is None:
            return _fail(f'item {index} failed prepare_broker_pick_for_import')
        if not str(prepared.get('prediction_id') or '').startswith('broker:'):
            return _fail(f'item {index} missing broker: prediction_id')

    print(f'[BROKER_COLLECTOR_VALIDATE] inbox_items={len(items)} file={OUTPUT_FILE}')
    print('BROKER_APP_COLLECTOR_VALIDATE_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
