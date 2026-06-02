#!/usr/bin/env python3
"""
Test bulk historical import (mock universe, no network).

Prints BULK_HISTORICAL_IMPORT_TEST_OK on success.
"""

from __future__ import annotations

import json
import sys
import tempfile
from datetime import datetime, timedelta
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
    range_progress_entry,
)

TEST_TICKER_A = '__TEST_BULK_A__'
TEST_TICKER_B = '__TEST_BULK_B__'


def _fail(msg: str) -> int:
    print(f'BULK_HISTORICAL_IMPORT_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def _mock_run_import(**kwargs) -> dict:
    tickers = kwargs.get('tickers') or []
    dry_run = kwargs.get('dry_run', False)
    rows_valid = 3 * len(tickers)
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


def _seed_full_coverage(*, market: str, ticker: str, from_date: str, to_date: str) -> None:
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
                'source': 'yfinance',
                'open': 100.0,
                'high': 101.0,
                'low': 99.0,
                'close': 100.5,
                'volume': 1000.0,
                'fake_prices': 0,
            })
        current += timedelta(days=1)
    upsert_prices(rows)


def main() -> int:
    from backend.storage.historical_market_store import get_connection, init_db
    from backend.storage.market_memory_db import get_market_memory_stats, init_market_memory_db
    import scripts.bulk_import_historical_prices as bulk_mod

    if not init_db() or not init_market_memory_db():
        return _fail('db init failed')

    stats_before = get_market_memory_stats()
    preds_before = int(stats_before.get('predictions') or 0)
    from_d, to_d = compute_date_range(years=1, from_date=None, to_date=None)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        universe_path = tmp_path / 'historical_ticker_universe.json'
        progress_path = tmp_path / 'historical_import_progress.json'
        report_path = tmp_path / 'historical_import_report.json'

        universe_path.write_text(
            json.dumps({
                'generated_at': '2026-05-01T00:00:00+00:00',
                'market': 'INDIA',
                'tickers': [
                    {'ticker': TEST_TICKER_A, 'sources': ['yfinance'], 'priority': 1},
                    {'ticker': TEST_TICKER_B, 'sources': ['yfinance'], 'priority': 1},
                ],
                'summary': {'total': 2},
            }),
            encoding='utf-8',
        )

        patches = (
            patch.object(bulk_mod, 'UNIVERSE_PATH', universe_path),
            patch.object(bulk_mod, 'PROGRESS_PATH', progress_path),
            patch.object(bulk_mod, 'REPORT_PATH', report_path),
            patch('scripts.import_historical_prices.run_import', side_effect=_mock_run_import),
            patch.object(bulk_mod, 'time'),
        )
        with patches[0], patches[1], patches[2], patches[3], patches[4] as mock_time:
            mock_time.sleep = lambda _s: None
            report1 = bulk_mod.run_bulk_import(
                market='INDIA',
                years=1,
                limit=2,
                batch_size=1,
                sleep_seconds=0,
                dry_run=True,
                resume=False,
                verbose=False,
            )

        if report1.get('fake_prices') != 0:
            return _fail('dry_run fake_prices != 0')
        if report1.get('tickers_total') != 2:
            return _fail('tickers_total != 2')
        if len(report1.get('batches') or []) != 2:
            return _fail('expected 2 batches with batch_size=1')
        if not report_path.is_file():
            return _fail('import report not written')

        _seed_full_coverage(
            market='INDIA',
            ticker=TEST_TICKER_A,
            from_date=from_d,
            to_date=to_d,
        )

        one_entry = range_progress_entry(
            market='INDIA',
            ticker=TEST_TICKER_A,
            from_date=from_d,
            to_date=to_d,
            years=1,
            source=DEFAULT_PROGRESS_SOURCE,
        )
        progress_path.write_text(
            json.dumps({
                'market': 'INDIA',
                'years': 1,
                'from_date': from_d,
                'to_date': to_d,
                'completed_ranges': [one_entry],
                'completed_tickers': [TEST_TICKER_A],
                'failed_tickers': [],
            }),
            encoding='utf-8',
        )

        with patches[0], patches[1], patches[2], patches[3], patches[4] as mock_time:
            mock_time.sleep = lambda _s: None
            report2 = bulk_mod.run_bulk_import(
                market='INDIA',
                years=1,
                limit=2,
                batch_size=2,
                sleep_seconds=0,
                dry_run=False,
                resume=True,
                verbose=False,
            )

        if report2.get('skipped_resume', 0) < 1:
            return _fail('resume did not skip imported ticker')
        if not progress_path.is_file():
            return _fail('progress file not written on write run')

        progress = json.loads(progress_path.read_text(encoding='utf-8'))
        completed_ranges = progress.get('completed_ranges') or []
        completed_tickers = {
            str(entry.get('ticker'))
            for entry in completed_ranges
            if isinstance(entry, dict) and entry.get('ticker')
        }
        if TEST_TICKER_B not in completed_tickers:
            return _fail('progress missing completed ticker B range entry')

    conn = get_connection()
    try:
        conn.execute('DELETE FROM historical_prices WHERE ticker LIKE ?', ('__TEST_BULK_%',))
        conn.commit()
    finally:
        conn.close()

    stats_after = get_market_memory_stats()
    preds_after = int(stats_after.get('predictions') or 0)
    if preds_before != preds_after:
        return _fail('canonical prediction count changed during test')

    print('BULK_HISTORICAL_IMPORT_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
