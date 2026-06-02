#!/usr/bin/env python3
"""
Inspect market memory learning summary and grouped performance.

Usage:
  python scripts/inspect_market_memory_learning.py
  python scripts/inspect_market_memory_learning.py --group-by confidence
  python scripts/inspect_market_memory_learning.py --ticker RELIANCE
  python scripts/inspect_market_memory_learning.py --json
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


def _format_rate(value: object) -> str:
    if value is None:
        return 'N/A'
    try:
        return f'{float(value) * 100:.2f}%'
    except (TypeError, ValueError):
        return 'N/A'


def _format_move(value: object) -> str:
    if value is None:
        return 'N/A'
    try:
        return f'{float(value):.4f}'
    except (TypeError, ValueError):
        return 'N/A'


def _print_overall(overall: dict) -> None:
    print(f"[LEARNING] total_predictions={overall.get('total_predictions', 0)}")
    print(f"[LEARNING] resolved_outcomes={overall.get('resolved_outcomes', 0)}")
    print(f"[LEARNING] wins={overall.get('wins', 0)}")
    print(f"[LEARNING] losses={overall.get('losses', 0)}")
    print(f"[LEARNING] win_rate={_format_rate(overall.get('win_rate'))}")
    print(f"[LEARNING] unresolved={overall.get('unresolved_predictions', 0)}")
    warnings = overall.get('warnings') or []
    if warnings:
        print(f"[LEARNING] warnings={','.join(warnings)}")


def _print_group_table(title: str, groups: dict) -> None:
    if not groups:
        print(f"[LEARNING] {title}: (empty)")
        return
    print(f"[LEARNING] {title}:")
    print('  key | resolved | wins | losses | win_rate | avg_move | warnings')
    for key in sorted(groups.keys()):
        item = groups[key]
        warnings = ','.join(item.get('warnings') or []) or '-'
        print(
            f"  {key} | {item.get('resolved', 0)} | {item.get('wins', 0)} | "
            f"{item.get('losses', 0)} | {_format_rate(item.get('win_rate'))} | "
            f"{_format_move(item.get('avg_actual_move'))} | {warnings}"
        )


def _print_grouped_list(title: str, groups: list[dict]) -> None:
    if not groups:
        print(f"[LEARNING] {title}: (empty)")
        return
    print(f"[LEARNING] {title}:")
    print('  key | resolved | wins | losses | win_rate | avg_move | warnings')
    for item in groups:
        warnings = ','.join(item.get('warnings') or []) or '-'
        print(
            f"  {item.get('key')} | {item.get('resolved', 0)} | {item.get('wins', 0)} | "
            f"{item.get('losses', 0)} | {_format_rate(item.get('win_rate'))} | "
            f"{_format_move(item.get('avg_actual_move'))} | {warnings}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description='Inspect market memory learning summary.')
    parser.add_argument('--ticker', help='Show performance for a single ticker')
    parser.add_argument(
        '--group-by',
        choices=('confidence', 'source', 'signal_type', 'horizon', 'ticker', 'broker_consensus'),
        help='Show grouped performance for one dimension',
    )
    parser.add_argument('--json', action='store_true', help='Print JSON output')
    parser.add_argument('--limit-days', type=int, default=None, help='Limit to recent N days')
    args = parser.parse_args()

    from backend.analytics.market_memory_learning import (
        get_grouped_performance,
        get_learning_summary,
        get_ticker_performance,
    )

    if args.ticker:
        payload = get_ticker_performance(args.ticker, limit_days=args.limit_days)
        if args.json:
            print(json.dumps(payload, indent=2, default=str))
            return 0 if payload.get('ok') else 1
        if not payload.get('ok'):
            print(f"[LEARNING] error={payload.get('error')}", file=sys.stderr)
            return 1
        perf = payload.get('performance') or {}
        print(f"[LEARNING] ticker={payload.get('ticker')}")
        print(f"[LEARNING] resolved={perf.get('resolved', 0)}")
        print(f"[LEARNING] wins={perf.get('wins', 0)}")
        print(f"[LEARNING] losses={perf.get('losses', 0)}")
        print(f"[LEARNING] win_rate={_format_rate(perf.get('win_rate'))}")
        print(f"[LEARNING] avg_actual_move={_format_move(perf.get('avg_actual_move'))}")
        warnings = perf.get('warnings') or []
        if warnings:
            print(f"[LEARNING] warnings={','.join(warnings)}")
        return 0

    if args.group_by:
        payload = get_grouped_performance(args.group_by, limit_days=args.limit_days)
        if args.json:
            print(json.dumps(payload, indent=2, default=str))
            return 0 if payload.get('ok') else 1
        if not payload.get('ok'):
            print(f"[LEARNING] error={payload.get('error')}", file=sys.stderr)
            return 1
        summary = get_learning_summary(limit_days=args.limit_days)
        _print_overall(summary.get('overall') or {})
        _print_grouped_list(f"group_by={args.group_by}", payload.get('groups') or [])
        return 0

    summary = get_learning_summary(limit_days=args.limit_days)
    if args.json:
        print(json.dumps(summary, indent=2, default=str))
        return 0

    overall = summary.get('overall') or {}
    _print_overall(overall)
    _print_group_table('by_confidence_label', summary.get('by_confidence_label') or {})
    _print_group_table('by_source', summary.get('by_source') or {})
    _print_group_table('by_signal_type', summary.get('by_signal_type') or {})
    _print_group_table('by_prediction_horizon', summary.get('by_prediction_horizon') or {})
    _print_group_table('by_broker_consensus', summary.get('by_broker_consensus') or {})
    _print_group_table('by_ticker', summary.get('by_ticker') or {})
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
