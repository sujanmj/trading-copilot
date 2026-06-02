#!/usr/bin/env python3
"""
Compact CLI for unified market memory dashboard payload.

Usage:
  python scripts/inspect_market_memory_dashboard.py
  python scripts/inspect_market_memory_dashboard.py --limit 30
  python scripts/inspect_market_memory_dashboard.py --json
  python scripts/inspect_market_memory_dashboard.py --price-file data/latest_market_data_memory_enriched.json
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


def _format_win_rate(value: object) -> str:
    if value is None:
        return '-'
    try:
        return f'{float(value):.4f}'
    except (TypeError, ValueError):
        return str(value)


def _print_compact(dashboard: dict) -> None:
    stats = dashboard.get('stats') or {}
    learning = dashboard.get('learning') or {}
    overall = learning.get('overall') if isinstance(learning.get('overall'), dict) else {}
    advisor = dashboard.get('advisor') or {}
    price_coverage = dashboard.get('price_coverage') or {}
    outcome_audit = dashboard.get('outcome_audit') or {}
    warnings = dashboard.get('warnings') or []

    print(f"[DASHBOARD] predictions={stats.get('predictions', 0)}")
    print(f"[DASHBOARD] outcomes={stats.get('outcomes', 0)}")
    print(f"[DASHBOARD] win_rate={_format_win_rate(overall.get('win_rate'))}")
    print(f"[DASHBOARD] advisor_caution={advisor.get('caution', 0)}")
    print(f"[DASHBOARD] advisor_neutral={advisor.get('neutral', 0)}")
    print(f"[DASHBOARD] price_symbols={price_coverage.get('symbols', 0)}")
    print(f"[DASHBOARD] outcome_anomalies={outcome_audit.get('anomalies', 0)}")
    print(f"[DASHBOARD] warnings={warnings}")


def main() -> int:
    from backend.analytics.market_memory_dashboard import (
        DEFAULT_DASHBOARD_PRICE_FILE,
        get_market_memory_dashboard,
    )

    parser = argparse.ArgumentParser(
        description='Inspect unified market memory dashboard payload (read-only)',
    )
    parser.add_argument('--limit', type=int, default=50, help='Row limit for latest/advisor sections')
    parser.add_argument('--json', action='store_true', help='Print full JSON payload')
    parser.add_argument(
        '--price-file',
        default=str(DEFAULT_DASHBOARD_PRICE_FILE),
        help='Market price JSON for coverage audit',
    )
    args = parser.parse_args()

    dashboard = get_market_memory_dashboard(
        limit=args.limit,
        price_file=args.price_file,
    )

    if args.json:
        print(json.dumps(dashboard, indent=2, default=str))
        return 0

    _print_compact(dashboard)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
