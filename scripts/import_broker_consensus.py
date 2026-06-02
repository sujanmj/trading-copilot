#!/usr/bin/env python3
"""
Import broker/source picks from a local JSON inbox into canonical_market_memory.db.

Usage:
  python scripts/import_broker_consensus.py
  python scripts/import_broker_consensus.py --file data/broker_consensus_inbox.json
  python scripts/import_broker_consensus.py --dry-run --verbose
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

DEFAULT_INBOX = PROJECT_ROOT / 'data' / 'broker_consensus_inbox.json'


def _load_items(path: Path) -> list[dict]:
    with path.open(encoding='utf-8') as handle:
        payload = json.load(handle)
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and isinstance(payload.get('items'), list):
        return payload['items']
    raise ValueError('JSON must be a list or an object with an "items" array')


def _is_valid_item(item: object) -> bool:
    if not isinstance(item, dict):
        return False
    broker_source = item.get('broker_source')
    ticker = item.get('ticker')
    return bool(str(broker_source or '').strip() and str(ticker or '').strip())


def main() -> int:
    parser = argparse.ArgumentParser(
        description='Import broker consensus picks from a local JSON inbox'
    )
    parser.add_argument(
        '--file',
        default=str(DEFAULT_INBOX),
        help='Path to broker consensus inbox JSON (default: data/broker_consensus_inbox.json)',
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Validate inbox without writing to the database',
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

    print(f'[BROKER_IMPORT] file={inbox_path}')
    print(f'[BROKER_IMPORT] dry_run={args.dry_run}')

    if not inbox_path.exists():
        print(
            f'[BROKER_IMPORT] inbox file not found: {inbox_path} '
            '(copy data/broker_consensus_inbox.example.json to get started)'
        )
        print('[BROKER_IMPORT] found=0')
        print('[BROKER_IMPORT] written=0')
        print('[BROKER_IMPORT] skipped=0')
        return 0

    try:
        items = _load_items(inbox_path)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f'[BROKER_IMPORT] error reading inbox: {exc}', file=sys.stderr)
        print('[BROKER_IMPORT] found=0')
        print('[BROKER_IMPORT] written=0')
        print('[BROKER_IMPORT] skipped=0')
        return 1

    print(f'[BROKER_IMPORT] found={len(items)}')

    written = 0
    skipped = 0

    if not args.dry_run:
        from backend.analytics.broker_consensus_engine import upsert_broker_pick

    for index, item in enumerate(items, start=1):
        if not _is_valid_item(item):
            skipped += 1
            if args.verbose:
                print(f'[BROKER_IMPORT] skip item {index}: missing broker_source or ticker')
            continue

        payload = dict(item)
        if payload.get('notes') is not None and payload.get('raw_payload') is None:
            payload['raw_payload'] = {'notes': payload.pop('notes')}

        if args.dry_run:
            written += 1
            if args.verbose:
                print(
                    f'[BROKER_IMPORT] dry-run item {index}: '
                    f"{payload.get('broker_source')} | {payload.get('ticker')}"
                )
            continue

        row_id = upsert_broker_pick(payload)
        if row_id is None:
            skipped += 1
            if args.verbose:
                print(
                    f'[BROKER_IMPORT] skip item {index}: upsert failed for '
                    f"{payload.get('broker_source')} | {payload.get('ticker')}"
                )
        else:
            written += 1
            if args.verbose:
                print(
                    f'[BROKER_IMPORT] wrote item {index}: id={row_id} '
                    f"{payload.get('broker_source')} | {payload.get('ticker')}"
                )

    print(f'[BROKER_IMPORT] written={written}')
    print(f'[BROKER_IMPORT] skipped={skipped}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
