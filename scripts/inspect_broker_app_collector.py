#!/usr/bin/env python3
"""
Inspect broker/app collector cache.

Usage:
  python scripts/inspect_broker_app_collector.py
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


def main() -> int:
    from backend.collectors.broker_app_collector import CACHE_FILE, load_collector_cache

    cache = load_collector_cache()
    exists = CACHE_FILE.is_file()
    summary = cache.get('summary') if isinstance(cache.get('summary'), dict) else {}

    if not summary and isinstance(cache.get('items'), list):
        from backend.collectors.broker_app_collector import _summarize_items

        summary = _summarize_items(cache.get('items') or [])

    ticker_count = summary.get('tickers', 0)
    if isinstance(ticker_count, list):
        ticker_count = len(ticker_count)

    print(f'[BROKER_COLLECTOR] cache_exists={exists}')
    print(f"[BROKER_COLLECTOR] total={summary.get('total', len(cache.get('items') or []))}")
    print(f"[BROKER_COLLECTOR] sources={summary.get('sources', [])}")
    print(f"[BROKER_COLLECTOR] tickers={ticker_count}")
    print(
        f"[BROKER_COLLECTOR] bullish={summary.get('bullish', 0)} "
        f"bearish={summary.get('bearish', 0)} watch={summary.get('watch', 0)} "
        f"neutral={summary.get('neutral', 0)}"
    )
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
