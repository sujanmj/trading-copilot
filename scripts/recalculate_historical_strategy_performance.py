#!/usr/bin/env python3
"""
Rebuild historical_strategy_performance from simulated_outcomes only.

Usage:
  python scripts/recalculate_historical_strategy_performance.py
  python scripts/recalculate_historical_strategy_performance.py --market INDIA

Prints HISTORICAL_STRATEGY_PERFORMANCE_RECALC_OK on success.
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
    print(f'HISTORICAL_STRATEGY_PERFORMANCE_RECALC_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description='Recalculate historical strategy performance aggregates.',
    )
    parser.add_argument('--market', choices=('INDIA', 'USA'), default=None)
    args = parser.parse_args()

    from backend.storage.historical_market_store import init_db, rebuild_strategy_performance

    if not init_db():
        return _fail('init_db returned False')

    rows_written = rebuild_strategy_performance(market=args.market)
    print(f'[HIST_STRAT_RECALC] rows_written={rows_written}')
    print('HISTORICAL_STRATEGY_PERFORMANCE_RECALC_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
