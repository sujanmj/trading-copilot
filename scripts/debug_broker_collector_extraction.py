#!/usr/bin/env python3
"""
Debug broker/app collector extraction from local source files.

Usage:
  python scripts/debug_broker_collector_extraction.py --source all --limit 50
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
    print(f'BROKER_COLLECTOR_EXTRACTION_DEBUG_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description='Debug broker collector extraction from local files.')
    parser.add_argument('--source', default='all', choices=('all', 'news', 'tv', 'manual'))
    parser.add_argument('--limit', type=int, default=50)
    args = parser.parse_args()

    from backend.collectors.broker_app_collector import debug_broker_collector_extraction

    result = debug_broker_collector_extraction(source=args.source, limit=args.limit)
    if not isinstance(result, dict):
        return _fail('debug returned invalid payload')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
