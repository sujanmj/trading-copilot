#!/usr/bin/env python3
"""
Inspect historical learning summary and replay stats.

Usage:
  python scripts/inspect_historical_learning.py
  python scripts/inspect_historical_learning.py --ticker RELIANCE
  python scripts/inspect_historical_learning.py --json
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


def main() -> int:
    parser = argparse.ArgumentParser(description='Inspect historical learning summary.')
    parser.add_argument('--ticker', help='Show performance for a single ticker')
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args()

    from backend.analytics.historical_learning_engine import (
        compare_live_memory_vs_historical,
        get_historical_learning_summary,
        get_historical_ticker_performance,
    )

    if args.ticker:
        payload = get_historical_ticker_performance(args.ticker)
        if args.json:
            print(json.dumps(payload, indent=2, default=str))
            return 0 if payload.get('ok') else 1
        if not payload.get('ok'):
            print(f"[HISTORICAL_LEARNING] error={payload.get('error')}", file=sys.stderr)
            return 1
        overall = payload.get('overall') or {}
        print(f"[HISTORICAL_LEARNING] ticker={payload.get('ticker')}")
        print(f"[HISTORICAL_LEARNING] wins={overall.get('wins', 0)}")
        print(f"[HISTORICAL_LEARNING] losses={overall.get('losses', 0)}")
        print(f"[HISTORICAL_LEARNING] ambiguous={overall.get('ambiguous', 0)}")
        print(f"[HISTORICAL_LEARNING] win_rate={_format_rate(overall.get('win_rate'))}")
        return 0

    summary = get_historical_learning_summary()
    comparison = compare_live_memory_vs_historical()
    if args.json:
        print(json.dumps({'summary': summary, 'comparison': comparison}, indent=2, default=str))
        return 0

    stats = summary.get('stats') or {}
    overall = summary.get('overall') or {}
    print(f"[HISTORICAL_LEARNING] db_path={stats.get('db_path')}")
    print(f"[HISTORICAL_LEARNING] price_rows={stats.get('historical_prices', 0)}")
    print(f"[HISTORICAL_LEARNING] replay_rows={stats.get('historical_outcome_replay', 0)}")
    print(f"[HISTORICAL_LEARNING] fake_prices_rows={stats.get('fake_prices_rows', 0)}")
    print(f"[HISTORICAL_LEARNING] wins={overall.get('wins', 0)}")
    print(f"[HISTORICAL_LEARNING] losses={overall.get('losses', 0)}")
    print(f"[HISTORICAL_LEARNING] ambiguous={overall.get('ambiguous', 0)}")
    print(f"[HISTORICAL_LEARNING] win_rate={_format_rate(overall.get('win_rate'))}")

    top = summary.get('top_tickers') or []
    if top:
        print('[HISTORICAL_LEARNING] top_tickers:')
        for item in top[:5]:
            print(
                f"  {item.get('ticker')} | win_rate={_format_rate(item.get('win_rate'))} | "
                f"w/l={item.get('wins', 0)}/{item.get('losses', 0)} | ambiguous={item.get('ambiguous', 0)}"
            )

    warnings = overall.get('warnings') or []
    if warnings:
        print(f"[HISTORICAL_LEARNING] warnings={','.join(warnings)}")

    live = comparison.get('live_memory') or {}
    hist = comparison.get('historical_replay') or {}
    print(
        f"[HISTORICAL_LEARNING] compare live_win_rate={_format_rate(live.get('win_rate'))} "
        f"historical_win_rate={_format_rate(hist.get('win_rate'))}"
    )
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
