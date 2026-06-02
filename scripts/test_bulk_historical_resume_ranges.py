#!/usr/bin/env python3
"""
Test date-range aware bulk historical import resume (mock/temp, no network).

Prints BULK_HISTORICAL_RESUME_RANGE_OK on success.
"""

from __future__ import annotations

import json
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if str(Path.cwd().resolve()) != str(PROJECT_ROOT.resolve()):
    import os

    os.chdir(PROJECT_ROOT)

from backend.analytics.historical_coverage import (
    DEFAULT_PROGRESS_SOURCE,
    compute_date_range,
    progress_key,
    range_progress_entry,
)

TEST_TICKER = '__TEST_RESUME_RANGE__'


def _fail(msg: str) -> int:
    print(f'BULK_HISTORICAL_RESUME_RANGE_FAIL: {msg}', file=sys.stderr)
    return 1


def _mock_run_import(**kwargs) -> dict:
    tickers = kwargs.get('tickers') or []
    dry_run = kwargs.get('dry_run', False)
    rows_valid = 5 * len(tickers)
    return {
        'dry_run': dry_run,
        'market': kwargs.get('market'),
        'from_date': kwargs.get('from_date'),
        'to_date': kwargs.get('to_date'),
        'tickers': tickers,
        'rows_fetched': rows_valid,
        'rows_valid': rows_valid,
        'rows_written': 0 if dry_run else rows_valid,
        'fake_prices': 0,
        'failed_tickers': [],
        'fetcher_hits': {},
    }


def _seed_full_coverage(
    *,
    market: str,
    ticker: str,
    from_date: str,
    to_date: str,
    source: str = 'yfinance',
) -> None:
    from backend.storage.historical_market_store import upsert_prices

    start = datetime.strptime(from_date, '%Y-%m-%d').date()
    end = datetime.strptime(to_date, '%Y-%m-%d').date()
    rows = []
    current = start
    while current <= end:
        if current.weekday() < 5:
            rows.append({
                'market': market,
                'ticker': ticker,
                'date': current.strftime('%Y-%m-%d'),
                'source': source,
                'open': 100.0,
                'high': 101.0,
                'low': 99.0,
                'close': 100.5,
                'volume': 1000.0,
                'fake_prices': 0,
            })
        current += timedelta(days=1)
    upsert_prices(rows)


def _one_year_range() -> tuple[str, str, int]:
    end = datetime.now(timezone.utc).date()
    start = end - timedelta(days=365)
    return start.strftime('%Y-%m-%d'), end.strftime('%Y-%m-%d'), 1


def _three_year_range() -> tuple[str, str, int]:
    end = datetime.now(timezone.utc).date()
    start = end - timedelta(days=3 * 365)
    return start.strftime('%Y-%m-%d'), end.strftime('%Y-%m-%d'), 3


def main() -> int:
    from backend.storage.historical_market_store import get_connection, init_db, upsert_prices
    from backend.storage.market_memory_db import get_market_memory_stats, init_market_memory_db
    import scripts.bulk_import_historical_prices as bulk_mod

    if not init_db() or not init_market_memory_db():
        return _fail('db init failed')

    stats_before = get_market_memory_stats()
    preds_before = int(stats_before.get('predictions') or 0)

    one_from, one_to, one_years = _one_year_range()
    three_from, three_to, three_years = _three_year_range()

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        universe_path = tmp_path / 'historical_ticker_universe.json'
        progress_path = tmp_path / 'historical_import_progress.json'
        report_path = tmp_path / 'historical_import_report.json'

        universe_path.write_text(
            json.dumps({
                'generated_at': '2026-05-01T00:00:00+00:00',
                'market': 'INDIA',
                'tickers': [{'ticker': TEST_TICKER, 'sources': ['yfinance'], 'priority': 1}],
                'summary': {'total': 1},
            }),
            encoding='utf-8',
        )

        one_entry = range_progress_entry(
            market='INDIA',
            ticker=TEST_TICKER,
            from_date=one_from,
            to_date=one_to,
            years=one_years,
            source=DEFAULT_PROGRESS_SOURCE,
        )
        progress_path.write_text(
            json.dumps({
                'market': 'INDIA',
                'years': one_years,
                'from_date': one_from,
                'to_date': one_to,
                'completed_ranges': [one_entry],
                'completed_tickers': [TEST_TICKER],
            }),
            encoding='utf-8',
        )

        _seed_full_coverage(
            market='INDIA',
            ticker=TEST_TICKER,
            from_date=one_from,
            to_date=one_to,
        )

        with patch.object(bulk_mod, 'UNIVERSE_PATH', universe_path), \
             patch.object(bulk_mod, 'PROGRESS_PATH', progress_path), \
             patch.object(bulk_mod, 'REPORT_PATH', report_path), \
             patch('scripts.import_historical_prices.run_import', side_effect=_mock_run_import), \
             patch.object(bulk_mod, 'time') as mock_time:
            mock_time.sleep = lambda _s: None

            report_three = bulk_mod.run_bulk_import(
                market='INDIA',
                years=three_years,
                from_date=three_from,
                to_date=three_to,
                limit=1,
                batch_size=1,
                sleep_seconds=0,
                dry_run=False,
                resume=True,
                verbose=False,
            )

        if report_three.get('skipped_covered', 0) != 0:
            return _fail('3-year request must not skip ticker with only 1-year progress/coverage')
        if report_three.get('rows_written', 0) <= 0:
            return _fail('3-year request must fetch missing older range')
        if len(report_three.get('batches') or []) != 1:
            return _fail('3-year request expected one import batch')

        with patch.object(bulk_mod, 'UNIVERSE_PATH', universe_path), \
             patch.object(bulk_mod, 'PROGRESS_PATH', progress_path), \
             patch.object(bulk_mod, 'REPORT_PATH', report_path), \
             patch('scripts.import_historical_prices.run_import', side_effect=_mock_run_import), \
             patch.object(bulk_mod, 'time') as mock_time:
            mock_time.sleep = lambda _s: None

            report_one = bulk_mod.run_bulk_import(
                market='INDIA',
                years=one_years,
                from_date=one_from,
                to_date=one_to,
                limit=1,
                batch_size=1,
                sleep_seconds=0,
                dry_run=False,
                resume=True,
                verbose=False,
            )

        if report_one.get('skipped_covered', 0) != 1:
            return _fail('1-year request with full coverage should skip on resume')
        if len(report_one.get('batches') or []) != 0:
            return _fail('1-year skip should not run import batches')

        progress = json.loads(progress_path.read_text(encoding='utf-8'))
        keys = {
            str(entry.get('key'))
            for entry in (progress.get('completed_ranges') or [])
            if isinstance(entry, dict)
        }
        expected_one_key = progress_key(
            market='INDIA',
            ticker=TEST_TICKER,
            from_date=one_from,
            to_date=one_to,
            years=one_years,
            source=DEFAULT_PROGRESS_SOURCE,
        )
        if expected_one_key not in keys:
            return _fail('progress keys must include 1-year date range')

        with patch.object(bulk_mod, 'UNIVERSE_PATH', universe_path), \
             patch.object(bulk_mod, 'PROGRESS_PATH', progress_path), \
             patch.object(bulk_mod, 'REPORT_PATH', report_path), \
             patch('scripts.import_historical_prices.run_import', side_effect=_mock_run_import), \
             patch.object(bulk_mod, 'time') as mock_time:
            mock_time.sleep = lambda _s: None

            report_ignore = bulk_mod.run_bulk_import(
                market='INDIA',
                years=one_years,
                from_date=one_from,
                to_date=one_to,
                limit=1,
                batch_size=1,
                sleep_seconds=0,
                dry_run=False,
                resume=True,
                ignore_progress=True,
                verbose=False,
            )

        if report_ignore.get('skipped_covered', 0) != 1:
            return _fail('--ignore-progress should still skip when DB coverage is complete')
        if len(report_ignore.get('batches') or []) != 0:
            return _fail('--ignore-progress with full DB coverage should not import')

        with patch.object(bulk_mod, 'UNIVERSE_PATH', universe_path), \
             patch.object(bulk_mod, 'PROGRESS_PATH', progress_path), \
             patch.object(bulk_mod, 'REPORT_PATH', report_path), \
             patch('scripts.import_historical_prices.run_import', side_effect=_mock_run_import), \
             patch.object(bulk_mod, 'time') as mock_time:
            mock_time.sleep = lambda _s: None

            report_force = bulk_mod.run_bulk_import(
                market='INDIA',
                years=one_years,
                from_date=one_from,
                to_date=one_to,
                limit=1,
                batch_size=1,
                sleep_seconds=0,
                dry_run=False,
                resume=True,
                force_range_check=True,
                verbose=False,
            )

        if report_force.get('skipped_covered', 0) != 1:
            return _fail('--force-range-check should skip when DB coverage is complete')

    conn = get_connection()
    try:
        conn.execute('DELETE FROM historical_prices WHERE ticker = ?', (TEST_TICKER,))
        conn.commit()
    finally:
        conn.close()

    stats_after = get_market_memory_stats()
    preds_after = int(stats_after.get('predictions') or 0)
    if preds_before != preds_after:
        return _fail('canonical prediction count changed during test')

    print('BULK_HISTORICAL_RESUME_RANGE_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
