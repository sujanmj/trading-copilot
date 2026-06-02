#!/usr/bin/env python3
"""
Batch shadow advisor report for unresolved market memory predictions.

Usage:
  python scripts/inspect_market_memory_advisor_batch.py --limit 30
  python scripts/inspect_market_memory_advisor_batch.py --advice caution --limit 30
  python scripts/inspect_market_memory_advisor_batch.py --ticker RELIANCE
  python scripts/inspect_market_memory_advisor_batch.py --json
  python scripts/inspect_market_memory_advisor_batch.py --output data/market_memory_advisor_report.json
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
        return '-'
    if isinstance(warnings, list):
        return ','.join(str(item) for item in warnings) or '-'
    return str(warnings)


def _print_summary(report: dict) -> None:
    print(f"[ADVISOR_BATCH] checked={report.get('checked', 0)}")
    print(f"[ADVISOR_BATCH] boost={report.get('boost', 0)}")
    print(f"[ADVISOR_BATCH] neutral={report.get('neutral', 0)}")
    print(f"[ADVISOR_BATCH] caution={report.get('caution', 0)}")
    print(f"[ADVISOR_BATCH] avoid_candidate={report.get('avoid_candidate', 0)}")
    print(f"[ADVISOR_BATCH] shadow_mode={report.get('shadow_mode')}")


def _print_table(rows: list[dict]) -> None:
    if not rows:
        print('[ADVISOR_BATCH] rows: (empty)')
        return

    print(
        'ticker | prediction_id | direction | confidence_label | signal_type | '
        'horizon | broker_consensus | advice | learning_score | warnings'
    )
    for row in rows:
        print(
            f"{row.get('ticker')} | {row.get('prediction_id')} | {row.get('direction')} | "
            f"{row.get('confidence_label')} | {row.get('signal_type')} | {row.get('horizon')} | "
            f"{row.get('broker_consensus')} | {row.get('advice')} | {row.get('learning_score')} | "
            f"{_format_warnings(row.get('warnings'))}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(
        description='Batch shadow advisor report for unresolved predictions.',
    )
    parser.add_argument('--limit', type=int, default=None, help='Max unresolved predictions to score')
    parser.add_argument(
        '--advice',
        choices=('boost', 'neutral', 'caution', 'avoid_candidate'),
        default=None,
        help='Filter rows by advice label',
    )
    parser.add_argument('--ticker', default=None, help='Filter by ticker symbol')
    parser.add_argument('--json', action='store_true', help='Print JSON output')
    parser.add_argument(
        '--output',
        default=None,
        help='Write JSON report to file (only when passed)',
    )
    args = parser.parse_args()

    from backend.analytics.market_memory_advisor import get_advisor_batch_report

    report = get_advisor_batch_report(
        limit=args.limit,
        advice=args.advice,
        ticker=args.ticker,
    )

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report, indent=2, default=str), encoding='utf-8')
        print(f'[ADVISOR_BATCH] wrote={output_path}')

    if args.json:
        print(json.dumps(report, indent=2, default=str))
        return 0

    _print_table(report.get('rows') or [])
    _print_summary(report)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
