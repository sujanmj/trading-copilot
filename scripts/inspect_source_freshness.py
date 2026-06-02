#!/usr/bin/env python3
"""
Compact CLI for local source freshness report.

Usage:
  python scripts/inspect_source_freshness.py
  python scripts/inspect_source_freshness.py --json
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


def _format_warnings(warnings: object) -> str:
    if not warnings:
        return '[]'
    if isinstance(warnings, list):
        return '[' + ','.join(str(item) for item in warnings) + ']'
    return str(warnings)


def main() -> int:
    parser = argparse.ArgumentParser(description='Inspect local source freshness (read-only)')
    parser.add_argument('--json', action='store_true', help='Print full JSON payload')
    args = parser.parse_args()

    from backend.analytics.source_freshness import get_source_freshness_report

    report = get_source_freshness_report()

    if args.json:
        print(json.dumps(report, indent=2, default=str))
        return 0

    print(f"[FRESHNESS] market_status={report.get('market_status')}")
    print(f"[FRESHNESS] runtime_snapshot_age_hours={report.get('runtime_snapshot_age_hours')}")
    print(f"[FRESHNESS] latest_market_data_age_hours={report.get('latest_market_data_age_hours')}")
    print(f"[FRESHNESS] enriched_price_age_hours={report.get('enriched_price_age_hours')}")
    print(f"[FRESHNESS] news_age_hours={report.get('news_age_hours')}")
    print(f"[FRESHNESS] warnings={_format_warnings(report.get('warnings'))}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
