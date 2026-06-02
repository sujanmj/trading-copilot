#!/usr/bin/env python3
"""
Validate historical range coverage after bulk import.

Usage:
  python scripts/validate_historical_range_coverage.py --market INDIA --years 3 --limit 10
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if str(Path.cwd().resolve()) != str(PROJECT_ROOT.resolve()):
    import os

    os.chdir(PROJECT_ROOT)

from backend.analytics.historical_coverage import (
    COVERAGE_TOLERANCE_DAYS,
    VALID_YEARS,
    compute_date_range,
    summarize_coverage_for_tickers,
)
from backend.utils.config import DATA_DIR

UNIVERSE_PATH = DATA_DIR / 'historical_ticker_universe.json'


def _fail(msg: str) -> int:
    print(f'HISTORICAL_RANGE_COVERAGE_FAIL: {msg}', file=sys.stderr)
    return 1


def _load_tickers(*, ticker: str | None, limit: int | None) -> list[str]:
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
    from backend.storage.historical_market_store import get_connection, init_db

    if not init_db():
        return _fail('init_db failed')

    parser = argparse.ArgumentParser(description='Validate historical range coverage.')
    parser.add_argument('--market', required=True, choices=('INDIA', 'USA'))
    parser.add_argument('--years', type=int, choices=VALID_YEARS, required=True)
    parser.add_argument('--from', dest='from_date', help='Start date YYYY-MM-DD')
    parser.add_argument('--to', dest='to_date', help='End date YYYY-MM-DD')
    parser.add_argument('--ticker', help='Single ticker to validate')
    parser.add_argument('--limit', type=int, default=None)
    args = parser.parse_args()

    from_d, to_d = compute_date_range(
        years=args.years,
        from_date=args.from_date,
        to_date=args.to_date,
    )

    try:
        tickers = _load_tickers(ticker=args.ticker, limit=args.limit)
    except FileNotFoundError as exc:
        return _fail(str(exc))

    if not tickers:
        return _fail('no tickers to validate')

    conn = get_connection()
    try:
        fake_row = conn.execute(
            """
            SELECT COUNT(*) AS cnt
            FROM historical_prices
            WHERE market = ?
              AND ticker IN ({placeholders})
              AND date >= ? AND date <= ?
              AND fake_prices != 0
            """.format(placeholders=','.join('?' for _ in tickers)),
            [args.market, *tickers, from_d, to_d],
        ).fetchone()
        fake_count = int(fake_row['cnt'] or 0) if fake_row else 0
    finally:
        conn.close()

    if fake_count != 0:
        return _fail(f'fake_prices rows in range={fake_count}')

    summary = summarize_coverage_for_tickers(
        market=args.market,
        tickers=tickers,
        from_date=from_d,
        to_date=to_d,
    )

    if summary.get('missing') == len(tickers):
        return _fail('all tickers missing coverage in requested range')

    oldest_date = summary.get('oldest_date')
    if not oldest_date:
        return _fail('no oldest_date found for tickers in range')

    expected_start = datetime.strptime(from_d, '%Y-%m-%d').date()
    max_allowed_start = expected_start + timedelta(days=COVERAGE_TOLERANCE_DAYS + 20)
    oldest = datetime.strptime(str(oldest_date), '%Y-%m-%d').date()
    if oldest > max_allowed_start:
        return _fail(
            f'aggregate oldest_date={oldest_date} too recent for years={args.years} '
            f'(expected near {from_d})'
        )

    if args.ticker:
        per_ticker = (summary.get('per_ticker') or {}).get(args.ticker) or {}
        if per_ticker.get('status') == 'missing':
            return _fail(f'{args.ticker} missing coverage in requested range')

    print(f'[HISTORICAL_RANGE_COVERAGE] market={args.market}')
    print(f'[HISTORICAL_RANGE_COVERAGE] years={args.years}')
    print(f'[HISTORICAL_RANGE_COVERAGE] requested_from={from_d}')
    print(f'[HISTORICAL_RANGE_COVERAGE] requested_to={to_d}')
    print(f'[HISTORICAL_RANGE_COVERAGE] tickers={len(tickers)}')
    print(f'[HISTORICAL_RANGE_COVERAGE] fully_covered={summary["fully_covered"]}')
    print(f'[HISTORICAL_RANGE_COVERAGE] partial={summary["partial"]}')
    print(f'[HISTORICAL_RANGE_COVERAGE] oldest_date={oldest_date}')
    print(f'[HISTORICAL_RANGE_COVERAGE] newest_date={summary.get("newest_date")}')
    print('HISTORICAL_RANGE_COVERAGE_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
