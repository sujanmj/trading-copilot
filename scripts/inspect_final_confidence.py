#!/usr/bin/env python3
"""
Inspect final confidence fusion scores for active candidates.

Usage:
  python scripts/inspect_final_confidence.py --limit 30
  python scripts/inspect_final_confidence.py --ticker RELIANCE
  python scripts/inspect_final_confidence.py --json
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


def _format_list(items: object) -> str:
    if not items:
        return '-'
    if isinstance(items, list):
        return ','.join(str(item) for item in items) or '-'
    return str(items)


def _print_summary(report: dict) -> None:
    print(f"[FINAL_CONFIDENCE] checked={report.get('checked', 0)}")
    print(f"[FINAL_CONFIDENCE] buy_candidate={report.get('buy_candidate', 0)}")
    print(f"[FINAL_CONFIDENCE] watch={report.get('watch', 0)}")
    print(f"[FINAL_CONFIDENCE] avoid={report.get('avoid', 0)}")
    print(f"[FINAL_CONFIDENCE] no_decision={report.get('no_decision', 0)}")
    print(f"[FINAL_CONFIDENCE] shadow_mode={report.get('shadow_mode')}")


def _print_table(rows: list[dict]) -> None:
    if not rows:
        print('[FINAL_CONFIDENCE] rows: (empty)')
        return

    print(
        'ticker | prediction_id | direction | confidence_label | final_score | decision | '
        'total_adjustment | hard_warnings | warnings'
    )
    for row in rows:
        print(
            f"{row.get('ticker')} | {row.get('prediction_id')} | {row.get('direction')} | "
            f"{row.get('confidence_label')} | {row.get('final_score')} | {row.get('decision')} | "
            f"{row.get('total_adjustment')} | {_format_list(row.get('hard_warnings'))} | "
            f"{_format_list(row.get('warnings'))}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description='Inspect final confidence fusion scores.')
    parser.add_argument('--limit', type=int, default=50, help='Max candidates to score')
    parser.add_argument('--ticker', default=None, help='Filter by ticker symbol')
    parser.add_argument('--json', action='store_true', help='Print JSON output')
    args = parser.parse_args()

    from backend.analytics.final_confidence_fusion import score_all_candidates

    report = score_all_candidates(limit=args.limit, ticker=args.ticker)

    if args.json:
        print(json.dumps(report, indent=2, default=str))
        return 0

    rows = report.get('rows') or []
    _print_table(rows[: args.limit])
    _print_summary(report)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
