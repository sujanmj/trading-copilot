#!/usr/bin/env python3
"""Refresh TV / YouTube stock-market intelligence cache."""

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


def main() -> int:
    parser = argparse.ArgumentParser(description='Refresh TV intelligence collector')
    parser.add_argument('--dry-run', action='store_true', help='Collect without writing output file')
    parser.add_argument('--limit', type=int, default=30, help='Max videos to keep')
    parser.add_argument('--verbose', action='store_true', help='Verbose logging')
    args = parser.parse_args()

    from backend.collectors.tv_intelligence_collector import collect_tv_intelligence

    print('[TV_INTEL] started')
    result = collect_tv_intelligence(dry_run=args.dry_run, limit=args.limit, verbose=args.verbose)
    summary = result.get('summary') or {}
    print(f"[TV_INTEL] source={result.get('source')}")
    print(f"[TV_INTEL] videos={summary.get('total', 0)}")
    print(f"[TV_INTEL] live={summary.get('live_count', 0)}")
    print(f"[TV_INTEL] recent={summary.get('recent_count', 0)}")
    print('[TV_INTEL] output=data/tv_intelligence.json')
    print('TV_INTELLIGENCE_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
