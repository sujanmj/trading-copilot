#!/usr/bin/env python3
"""Reprocess My Feed item metadata with latest 50C extractor (Stage 50C hotfix)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description='Recompute My Feed tickers/themes/actions from stored text.')
    parser.add_argument('--dry-run', action='store_true', help='Preview changes without writing DB')
    parser.add_argument('--apply', action='store_true', help='Apply metadata updates to SQLite store')
    parser.add_argument('--limit', type=int, default=500, help='Max items to scan')
    args = parser.parse_args()

    if args.apply and args.dry_run:
        print('Choose either --dry-run or --apply, not both.', file=sys.stderr)
        return 1
    if not args.apply and not args.dry_run:
        args.dry_run = True

    from backend.my_feed.feed_reprocessor import reprocess_my_feed_items

    result = reprocess_my_feed_items(apply=bool(args.apply), limit=args.limit)
    print(json.dumps({
        'ok': result.get('ok'),
        'apply': result.get('apply'),
        'total': result.get('total'),
        'updated': result.get('updated'),
        'unchanged': result.get('unchanged'),
        'errors': result.get('errors'),
    }, indent=2))
    return 0 if result.get('ok') else 1


if __name__ == '__main__':
    raise SystemExit(main())
