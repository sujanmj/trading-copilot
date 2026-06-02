"""
Date-range aware historical price coverage checks for bulk import resume.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any

from backend.analytics.historical_price_audit import FAKE_SOURCE_PATTERN, TEST_TICKER_PREFIX

DEFAULT_PROGRESS_SOURCE = 'bulk_historical'
COVERAGE_TOLERANCE_DAYS = 10
VALID_YEARS = (1, 3, 5, 10)


def compute_date_range(
    *,
    years: int | None,
    from_date: str | None,
    to_date: str | None,
) -> tuple[str, str]:
    if from_date and to_date:
        return from_date, to_date
    end = datetime.now(timezone.utc).date()
    if years is None:
        years = 1
    start = end - timedelta(days=int(years) * 365)
    return start.strftime('%Y-%m-%d'), end.strftime('%Y-%m-%d')


def progress_key(
    *,
    market: str,
    ticker: str,
    from_date: str,
    to_date: str,
    years: int | None,
    source: str = DEFAULT_PROGRESS_SOURCE,
) -> str:
    years_token = str(years) if years is not None else 'custom'
    return '|'.join([
        str(market or '').strip().upper(),
        str(ticker or '').strip().upper(),
        from_date,
        to_date,
        years_token,
        str(source or DEFAULT_PROGRESS_SOURCE),
    ])


def _parse_date(value: str) -> datetime.date:
    return datetime.strptime(value, '%Y-%m-%d').date()


def _expected_trading_days(from_date: str, to_date: str) -> int:
    start = _parse_date(from_date)
    end = _parse_date(to_date)
    calendar_days = max(1, (end - start).days + 1)
    return max(5, int(calendar_days * 252 / 365))


def _is_real_price_row(*, ticker: str, source: str, fake_prices: int) -> bool:
    if int(fake_prices or 0) != 0:
        return False
    row_ticker = str(ticker or '').strip().upper()
    if row_ticker.startswith(TEST_TICKER_PREFIX):
        return False
    row_source = str(source or '')
    if FAKE_SOURCE_PATTERN.search(row_source):
        return False
    return True


def check_ticker_coverage(
    *,
    market: str,
    ticker: str,
    from_date: str,
    to_date: str,
) -> dict[str, Any]:
    """Return coverage status for one ticker over a requested date range."""
    from backend.storage.historical_market_store import get_connection, init_db

    init_db()
    normalized_market = str(market or '').strip().upper()
    normalized_ticker = str(ticker or '').strip().upper()

    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT date, source, fake_prices
            FROM historical_prices
            WHERE market = ? AND ticker = ?
            ORDER BY date ASC
            """,
            (normalized_market, normalized_ticker),
        ).fetchall()
    finally:
        conn.close()

    dates: set[str] = set()
    for row in rows:
        if not _is_real_price_row(
            ticker=normalized_ticker,
            source=str(row['source'] or ''),
            fake_prices=int(row['fake_prices'] or 0),
        ):
            continue
        date = str(row['date'] or '')
        if from_date <= date <= to_date:
            dates.add(date)

    row_count = len(dates)
    if row_count == 0:
        return {
            'status': 'missing',
            'oldest_date': None,
            'newest_date': None,
            'row_count': 0,
        }

    sorted_dates = sorted(dates)
    oldest_date = sorted_dates[0]
    newest_date = sorted_dates[-1]

    start_bound = _parse_date(from_date) + timedelta(days=COVERAGE_TOLERANCE_DAYS)
    end_bound = _parse_date(to_date) - timedelta(days=COVERAGE_TOLERANCE_DAYS)
    min_rows = max(5, int(_expected_trading_days(from_date, to_date) * 0.5))

    oldest_ok = _parse_date(oldest_date) <= start_bound
    newest_ok = _parse_date(newest_date) >= end_bound
    rows_ok = row_count >= min_rows

    if oldest_ok and newest_ok and rows_ok:
        status = 'fully_covered'
    else:
        status = 'partial'

    return {
        'status': status,
        'oldest_date': oldest_date,
        'newest_date': newest_date,
        'row_count': row_count,
    }


def should_skip_ticker_import(
    *,
    market: str,
    ticker: str,
    from_date: str,
    to_date: str,
    years: int | None,
    source: str = DEFAULT_PROGRESS_SOURCE,
    completed_range_keys: set[str],
    ignore_progress: bool = False,
    force_range_check: bool = False,
) -> tuple[bool, dict[str, Any]]:
    """Decide whether bulk import can skip a ticker for this exact range."""
    coverage = check_ticker_coverage(
        market=market,
        ticker=ticker,
        from_date=from_date,
        to_date=to_date,
    )
    if coverage['status'] != 'fully_covered':
        return False, coverage

    if ignore_progress or force_range_check:
        return True, coverage

    key = progress_key(
        market=market,
        ticker=ticker,
        from_date=from_date,
        to_date=to_date,
        years=years,
        source=source,
    )
    return key in completed_range_keys, coverage


def range_progress_entry(
    *,
    market: str,
    ticker: str,
    from_date: str,
    to_date: str,
    years: int | None,
    source: str = DEFAULT_PROGRESS_SOURCE,
) -> dict[str, Any]:
    return {
        'key': progress_key(
            market=market,
            ticker=ticker,
            from_date=from_date,
            to_date=to_date,
            years=years,
            source=source,
        ),
        'market': str(market or '').strip().upper(),
        'ticker': str(ticker or '').strip().upper(),
        'from_date': from_date,
        'to_date': to_date,
        'years': years,
        'source': source,
    }


def load_completed_range_keys(progress: dict[str, Any] | None) -> set[str]:
    if not progress:
        return set()
    keys: set[str] = set()
    for entry in progress.get('completed_ranges') or []:
        if isinstance(entry, dict):
            key = entry.get('key')
            if key:
                keys.add(str(key))
        elif isinstance(entry, str):
            keys.add(entry)
    return keys


def load_failed_range_keys(progress: dict[str, Any] | None) -> set[str]:
    if not progress:
        return set()
    keys: set[str] = set()
    for entry in progress.get('failed_ranges') or []:
        if isinstance(entry, dict):
            key = entry.get('key')
            if key:
                keys.add(str(key))
        elif isinstance(entry, str):
            keys.add(entry)
    return keys


def merge_completed_ranges(
    existing: list[Any],
    new_entries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    by_key: dict[str, dict[str, Any]] = {}
    for entry in existing or []:
        if isinstance(entry, dict) and entry.get('key'):
            by_key[str(entry['key'])] = entry
        elif isinstance(entry, str):
            by_key[entry] = {'key': entry}
    for entry in new_entries:
        by_key[str(entry['key'])] = entry
    return sorted(by_key.values(), key=lambda item: str(item.get('key') or ''))


def summarize_coverage_for_tickers(
    *,
    market: str,
    tickers: list[str],
    from_date: str,
    to_date: str,
) -> dict[str, Any]:
    fully_covered = 0
    partial = 0
    missing = 0
    oldest_dates: list[str] = []
    newest_dates: list[str] = []
    per_ticker: dict[str, dict[str, Any]] = {}

    for ticker in tickers:
        coverage = check_ticker_coverage(
            market=market,
            ticker=ticker,
            from_date=from_date,
            to_date=to_date,
        )
        per_ticker[ticker] = coverage
        status = coverage.get('status')
        if status == 'fully_covered':
            fully_covered += 1
        elif status == 'partial':
            partial += 1
        else:
            missing += 1
        if coverage.get('oldest_date'):
            oldest_dates.append(str(coverage['oldest_date']))
        if coverage.get('newest_date'):
            newest_dates.append(str(coverage['newest_date']))

    return {
        'fully_covered': fully_covered,
        'partial': partial,
        'missing': missing,
        'oldest_date': min(oldest_dates) if oldest_dates else None,
        'newest_date': max(newest_dates) if newest_dates else None,
        'per_ticker': per_ticker,
    }
