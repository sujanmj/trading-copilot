#!/usr/bin/env python3
"""
Inspect historical price coverage for bulk import ranges.

Usage:
  python scripts/inspect_historical_coverage.py --market INDIA --years 3 --limit 10
  python scripts/inspect_historical_coverage.py --market INDIA --years 1 --ticker RELIANCE
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

from backend.analytics.historical_coverage import (
    VALID_YEARS,
    compute_date_range,
    summarize_coverage_for_tickers,
)
from backend.utils.config import DATA_DIR

UNIVERSE_PATH = DATA_DIR / 'historical_ticker_universe.json'


def _fail(msg: str) -> int:
    print(f'HIST_COVERAGE_FAIL: {msg}', file=sys.stderr)
    return 1


def _load_tickers(*, market: str, ticker: str | None, limit: int | None) -> list[str]:
    from scripts.import_historical_prices import _normalize_ticker

    if ticker:
        return [_normalize_ticker(ticker)]

    if not UNIVERSE_PATH.is_file():
        raise FileNotFoundError(f'missing universe file: {UNIVERSE_PATH}')

    import json

    universe = json.loads(UNIVERSE_PATH.read_text(encoding='utf-8'))
    entries = universe.get('tickers') or []
    tickers = [
        _normalize_ticker(entry.get('ticker') if isinstance(entry, dict) else entry)
        for entry in entries
    ]
    tickers = [t for t in tickers if t]
    tickers.sort()
    if limit is not None and limit > 0:
        tickers = tickers[: int(limit)]
    return tickers


def main() -> int:
    parser = argparse.ArgumentParser(description='Inspect historical price coverage.')
    parser.add_argument('--market', required=True, choices=('INDIA', 'USA'))
    parser.add_argument('--years', type=int, choices=VALID_YEARS, default=1)
    parser.add_argument('--from', dest='from_date', help='Start date YYYY-MM-DD')
    parser.add_argument('--to', dest='to_date', help='End date YYYY-MM-DD')
    parser.add_argument('--ticker', help='Single ticker to inspect')
    parser.add_argument('--limit', type=int, default=None)
    args = parser.parse_args()

    from_d, to_d = compute_date_range(
        years=args.years,
        from_date=args.from_date,
        to_date=args.to_date,
    )

    try:
        tickers = _load_tickers(market=args.market, ticker=args.ticker, limit=args.limit)
    except FileNotFoundError as exc:
        return _fail(str(exc))

    if not tickers:
        return _fail('no tickers to inspect')

    summary = summarize_coverage_for_tickers(
        market=args.market,
        tickers=tickers,
        from_date=from_d,
        to_date=to_d,
    )

    print(f'[HIST_COVERAGE] market={args.market}')
    print(f'[HIST_COVERAGE] requested_from={from_d}')
    print(f'[HIST_COVERAGE] requested_to={to_d}')
    print(f'[HIST_COVERAGE] tickers={len(tickers)}')
    print(f'[HIST_COVERAGE] fully_covered={summary["fully_covered"]}')
    print(f'[HIST_COVERAGE] partial={summary["partial"]}')
    print(f'[HIST_COVERAGE] missing={summary["missing"]}')
    print(f'[HIST_COVERAGE] oldest_date={summary.get("oldest_date")}')
    print(f'[HIST_COVERAGE] newest_date={summary.get("newest_date")}')
    print('HISTORICAL_COVERAGE_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
