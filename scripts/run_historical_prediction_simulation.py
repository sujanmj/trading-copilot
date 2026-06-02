#!/usr/bin/env python3
"""
Run historical prediction simulation over OHLCV data.

Usage:
  python scripts/run_historical_prediction_simulation.py --market INDIA --years 1 --limit-tickers 10 --dry-run
  python scripts/run_historical_prediction_simulation.py --market INDIA --years 1 --limit-tickers 10 --write

Prints exactly HISTORICAL_SIMULATION_OK on success.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if str(Path.cwd().resolve()) != str(PROJECT_ROOT.resolve()):
    import os

    os.chdir(PROJECT_ROOT)


def _fail(msg: str) -> int:
    print(f'HISTORICAL_SIMULATION_FAIL: {msg}', file=sys.stderr)
    return 1


def _years_range(years: int) -> tuple[str, str]:
    today = datetime.now(timezone.utc).date()
    start = today - timedelta(days=int(years) * 365)
    return start.isoformat(), today.isoformat()


def main() -> int:
    parser = argparse.ArgumentParser(description='Run historical prediction simulation.')
    parser.add_argument('--market', choices=('INDIA', 'USA'), default='INDIA')
    parser.add_argument('--from', dest='from_date', help='Start date YYYY-MM-DD')
    parser.add_argument('--to', dest='to_date', help='End date YYYY-MM-DD')
    parser.add_argument('--years', type=int, choices=(1, 3, 5, 10), default=None)
    parser.add_argument(
        '--strategy',
        default='all',
        help='Strategy name or all (comma-separated)',
    )
    parser.add_argument('--limit-tickers', type=int, default=None)
    parser.add_argument('--max-signals-per-ticker-strategy', type=int, default=200)
    parser.add_argument('--dry-run', action='store_true', default=False)
    parser.add_argument('--write', action='store_true', default=False)
    parser.add_argument('--replace-existing', action='store_true', default=False)
    parser.add_argument('--allow-duplicate', action='store_true', default=False)
    parser.add_argument('--run-label', default=None, help='Optional label stored in params_json')
    parser.add_argument('--verbose', action='store_true')
    args = parser.parse_args()

    from_date = args.from_date
    to_date = args.to_date
    if args.years and not (from_date and to_date):
        from_date, to_date = _years_range(args.years)
    if not from_date or not to_date:
        from_date, to_date = _years_range(1)

    if args.strategy == 'all':
        strategies = None
    else:
        strategies = [token.strip() for token in args.strategy.split(',') if token.strip()]

    dry_run = not args.write

    from backend.analytics.historical_prediction_simulator import run_historical_simulation
    from backend.storage.market_memory_db import get_market_memory_stats

    stats_before = get_market_memory_stats()
    preds_before = int(stats_before.get('predictions') or 0)
    outcomes_before = int(stats_before.get('outcomes') or 0)

    summary = run_historical_simulation(
        market=args.market,
        from_date=from_date,
        to_date=to_date,
        years=args.years,
        strategies=strategies,
        limit_tickers=args.limit_tickers,
        max_signals=args.max_signals_per_ticker_strategy,
        dry_run=dry_run,
        write=args.write,
        verbose=args.verbose,
        replace_existing=args.replace_existing,
        allow_duplicate=args.allow_duplicate,
        run_label=args.run_label,
    )

    print(f'[HIST_SIM] run_id={summary.get("run_id")}')
    print(f'[HIST_SIM] params_hash={summary.get("params_hash")}')
    print(f'[HIST_SIM] market={summary.get("market")}')
    print(f'[HIST_SIM] tickers={summary.get("tickers", 0)}')
    print(f'[HIST_SIM] signals_generated={summary.get("signals_generated", 0)}')
    print(f'[HIST_SIM] resolved={summary.get("resolved", 0)}')
    print(f'[HIST_SIM] wins={summary.get("wins", 0)}')
    print(f'[HIST_SIM] losses={summary.get("losses", 0)}')
    print(f'[HIST_SIM] ambiguous={summary.get("ambiguous", 0)}')
    print(f'[HIST_SIM] written={summary.get("written", 0)}')
    print(f'[HIST_SIM] fake_predictions={summary.get("fake_predictions", 0)}')
    if summary.get('duplicate_existing_run'):
        print(f'[HIST_SIM] duplicate_existing_run={summary.get("duplicate_existing_run")}')

    stats_after = get_market_memory_stats()
    preds_after = int(stats_after.get('predictions') or 0)
    outcomes_after = int(stats_after.get('outcomes') or 0)
    if preds_before != preds_after or outcomes_before != outcomes_after:
        return _fail(
            f'canonical DB changed predictions {preds_before}->{preds_after} '
            f'outcomes {outcomes_before}->{outcomes_after}',
        )

    print('HISTORICAL_SIMULATION_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
