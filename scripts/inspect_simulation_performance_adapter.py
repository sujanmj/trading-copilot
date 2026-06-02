#!/usr/bin/env python3
"""
Inspect simulation performance adapter output.

Usage:
  python scripts/inspect_simulation_performance_adapter.py
  python scripts/inspect_simulation_performance_adapter.py --ticker RELIANCE
  python scripts/inspect_simulation_performance_adapter.py --json
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


def main() -> int:
    parser = argparse.ArgumentParser(description='Inspect simulation performance adapter.')
    parser.add_argument('--ticker', default=None, help='Optional ticker for ticker perf')
    parser.add_argument('--json', action='store_true', help='Emit JSON only')
    args = parser.parse_args()

    from backend.analytics.simulation_performance_adapter import (
        get_simulation_summary,
        get_strategy_performance,
        get_ticker_simulation_performance,
        infer_candidate_strategy,
        score_simulation_evidence,
    )

    summary = get_simulation_summary()
    strategies = get_strategy_performance()

    if args.json:
        payload = {'summary': summary, 'strategies': strategies}
        if args.ticker:
            payload['ticker'] = get_ticker_simulation_performance(args.ticker)
            payload['sample_candidate'] = score_simulation_evidence({'ticker': args.ticker})
        print(json.dumps(payload, indent=2, default=str))
        return 0

    stats = summary.get('stats') or {}
    rows = strategies.get('rows') or []
    print(f'[SIM_ADAPTER] simulation_predictions={stats.get("simulated_predictions", 0)}')
    print(f'[SIM_ADAPTER] simulation_outcomes={stats.get("simulated_outcomes", 0)}')
    print(f'[SIM_ADAPTER] strategies={len(rows)}')
    print('[SIM_ADAPTER] strategy | sample | win_rate | expectancy')
    for row in rows:
        sample = int(row.get('resolved') or 0)
        win_rate = row.get('win_rate')
        expectancy = row.get('expectancy_pct')
        warning = row.get('coverage_warning') or row.get('sample_warning')
        suffix = f' warning={warning}' if warning else ''
        print(
            f'[SIM_ADAPTER] {row.get("strategy")} | {sample} | {win_rate} | {expectancy}{suffix}',
        )

    if args.ticker:
        ticker_perf = get_ticker_simulation_performance(args.ticker)
        print(
            f'[SIM_ADAPTER] ticker={args.ticker} sample={ticker_perf.get("sample")} '
            f'win_rate={ticker_perf.get("win_rate")} expectancy={ticker_perf.get("expectancy_pct")}',
        )
        sample = score_simulation_evidence({'ticker': args.ticker, 'direction': 'BUY'})
        print(
            f'[SIM_ADAPTER] evidence adj={sample.get("confidence_adjustment")} '
            f'inferred={sample.get("inferred_strategy")} warnings={sample.get("warnings")}',
        )
        inference = infer_candidate_strategy({'ticker': args.ticker, 'signal_type': 'breakout'})
        print(f'[SIM_ADAPTER] infer_breakout={inference.get("inferred_strategy")}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
