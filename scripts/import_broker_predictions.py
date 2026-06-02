#!/usr/bin/env python3
"""
Import external broker/app picks into canonical_market_memory.db (broker_predictions only).

Usage:
  python scripts/import_broker_predictions.py
  python scripts/import_broker_predictions.py --file data/broker_prediction_inbox.json
  python scripts/import_broker_predictions.py --source Moneycontrol --dry-run --verbose
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

DEFAULT_INBOX = PROJECT_ROOT / 'data' / 'broker_prediction_inbox.json'


def _load_items(path: Path) -> tuple[list[dict], str | None]:
    with path.open(encoding='utf-8') as handle:
        payload = json.load(handle)
    file_source = None
    if isinstance(payload, dict):
        file_source = payload.get('source')
        items = payload.get('items')
        if isinstance(items, list):
            return items, str(file_source).strip() if file_source else None
    if isinstance(payload, list):
        return payload, None
    raise ValueError('JSON must be a list or an object with an "items" array')


def main() -> int:
    parser = argparse.ArgumentParser(
        description='Import broker prediction evidence from a local JSON inbox'
    )
    parser.add_argument(
        '--file',
        default=str(DEFAULT_INBOX),
        help='Path to broker prediction inbox JSON',
    )
    parser.add_argument(
        '--source',
        default=None,
        help='Default broker_source when items omit it',
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Validate inbox without writing to the database',
    )
    parser.add_argument(
        '--update-existing',
        action='store_true',
        help='Update rows that share the same deterministic broker ID',
    )
    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Print per-item import details',
    )
    args = parser.parse_args()

    inbox_path = Path(args.file)
    if not inbox_path.is_absolute():
        inbox_path = PROJECT_ROOT / inbox_path

    print(f'[BROKER_PREDICTIONS_IMPORT] file={inbox_path}')
    print(f'[BROKER_PREDICTIONS_IMPORT] dry_run={args.dry_run}')
    print(f'[BROKER_PREDICTIONS_IMPORT] update_existing={args.update_existing}')

    if not inbox_path.exists():
        print(
            f'[BROKER_PREDICTIONS_IMPORT] inbox not found: {inbox_path} '
            '(copy data/broker_prediction_inbox.example.json)'
        )
        print('[BROKER_PREDICTIONS_IMPORT] found=0 written=0 skipped=0 rejected=0')
        print('BROKER_PREDICTIONS_IMPORT_OK')
        return 0

    try:
        items, file_source = _load_items(inbox_path)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f'[BROKER_PREDICTIONS_IMPORT] error: {exc}', file=sys.stderr)
        return 1

    default_source = args.source or file_source
    print(f'[BROKER_PREDICTIONS_IMPORT] found={len(items)}')

    written = 0
    skipped = 0
    rejected = 0

    from backend.analytics.broker_prediction_intelligence import (
        is_outcome_evidence,
        prepare_broker_pick_for_import,
    )

    if not args.dry_run:
        from backend.storage.market_memory_db import init_market_memory_db, upsert_broker_prediction

        if not init_market_memory_db():
            print('[BROKER_PREDICTIONS_IMPORT] init_market_memory_db failed', file=sys.stderr)
            return 1

    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            skipped += 1
            if args.verbose:
                print(f'[BROKER_PREDICTIONS_IMPORT] skip item {index}: not an object')
            continue

        if is_outcome_evidence(item):
            rejected += 1
            if args.verbose:
                print(
                    f'[BROKER_PREDICTIONS_IMPORT] reject item {index}: '
                    f'outcome evidence ({item.get("ticker")})'
                )
            continue

        payload = prepare_broker_pick_for_import(item, source_hint=default_source)
        if payload is None:
            skipped += 1
            if args.verbose:
                print(f'[BROKER_PREDICTIONS_IMPORT] skip item {index}: invalid or empty')
            continue

        if args.dry_run:
            written += 1
            if args.verbose:
                print(
                    f'[BROKER_PREDICTIONS_IMPORT] dry-run item {index}: '
                    f"{payload.get('prediction_id')} | {payload.get('broker_source')} | "
                    f"{payload.get('ticker')} | {payload.get('bullish_or_bearish')}"
                )
            continue

        row_id = upsert_broker_prediction(payload, update_existing=args.update_existing)
        if row_id is None:
            skipped += 1
            if args.verbose:
                print(
                    f'[BROKER_PREDICTIONS_IMPORT] skip item {index}: upsert failed '
                    f"{payload.get('prediction_id')}"
                )
        else:
            written += 1
            if args.verbose:
                print(
                    f'[BROKER_PREDICTIONS_IMPORT] wrote item {index}: id={row_id} '
                    f"{payload.get('prediction_id')}"
                )

    print(f'[BROKER_PREDICTIONS_IMPORT] written={written}')
    print(f'[BROKER_PREDICTIONS_IMPORT] skipped={skipped}')
    print(f'[BROKER_PREDICTIONS_IMPORT] rejected={rejected}')
    print('BROKER_PREDICTIONS_IMPORT_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
