"""
Audit historical_prices quality in historical_market_memory.db.
"""

from __future__ import annotations

import math
import re
from typing import Any

from backend.analytics.historical_symbol_mapping import normalize_historical_ticker

FAKE_SOURCE_PATTERN = re.compile(r'fake|test|mock|synthetic', re.IGNORECASE)
TEST_TICKER_PREFIX = '__TEST__'
MAX_DAILY_MOVE_PCT = 40.0
SCALE_DISCONTINUITY_RATIO_HIGH = 10.0
SCALE_DISCONTINUITY_RATIO_LOW = 0.1


def severity_for_reason(reason: str) -> str:
    """Map audit reason to quarantine severity."""
    token = str(reason or '').strip()
    if token == 'suspicious_daily_move':
        return 'warning'
    if token in (
        'scale_discontinuity',
        'high_lt_low',
        'nan_ohlc',
        'open_outside_range',
        'close_outside_range',
        'fake_prices_flag',
        'suspicious_source_or_ticker',
    ):
        return 'exclude_from_simulation'
    if token == 'duplicate_row':
        return 'suspicious'
    return 'warning'


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(num) or math.isinf(num):
        return None
    return num


def _anomaly_row(
    reason: str,
    *,
    market: str,
    ticker: str,
    date: str,
    source: str = '',
    open_val: float | None = None,
    high_val: float | None = None,
    low_val: float | None = None,
    close_val: float | None = None,
    volume_val: float | None = None,
    **extra: Any,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        'reason': reason,
        'type': reason,
        'market': market,
        'ticker': ticker,
        'date': date,
        'source': source,
        'open': open_val,
        'high': high_val,
        'low': low_val,
        'close': close_val,
        'volume': volume_val,
    }
    row.update(extra)
    row['severity'] = severity_for_reason(reason)
    return row


def audit_historical_prices(
    *,
    ticker: str | None = None,
    exclude_scale_discontinuity: bool = False,
) -> dict[str, Any]:
    """Return audit summary with anomaly details."""
    from backend.storage.historical_market_store import get_connection, init_db

    init_db()
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT market, ticker, date, source, open, high, low, close, volume, fake_prices
            FROM historical_prices
            ORDER BY ticker ASC, date ASC, source ASC
            """
        ).fetchall()
    finally:
        conn.close()

    filter_ticker = normalize_historical_ticker(ticker) if ticker else None

    anomalies: list[dict[str, Any]] = []
    tickers: set[str] = set()
    missing_volume = 0
    fake_prices = 0
    seen_keys: set[tuple[str, str, str, str]] = set()
    prev_close_by_ticker: dict[tuple[str, str], float] = {}

    for row in rows:
        market = str(row['market'] or '')
        row_ticker = str(row['ticker'] or '')
        date = str(row['date'] or '')
        source = str(row['source'] or '')

        if filter_ticker and normalize_historical_ticker(row_ticker) != filter_ticker:
            continue

        tickers.add(row_ticker)

        open_val = _safe_float(row['open'])
        high_val = _safe_float(row['high'])
        low_val = _safe_float(row['low'])
        close_val = _safe_float(row['close'])
        volume_val = _safe_float(row['volume'])

        key = (market, row_ticker, date, source)
        if key in seen_keys:
            anomalies.append(_anomaly_row(
                'duplicate_row',
                market=market,
                ticker=row_ticker,
                date=date,
                source=source,
                open_val=open_val,
                high_val=high_val,
                low_val=low_val,
                close_val=close_val,
                volume_val=volume_val,
            ))
        seen_keys.add(key)

        if int(row['fake_prices'] or 0) != 0:
            fake_prices += 1
            anomalies.append(_anomaly_row(
                'fake_prices_flag',
                market=market,
                ticker=row_ticker,
                date=date,
                source=source,
                open_val=open_val,
                high_val=high_val,
                low_val=low_val,
                close_val=close_val,
                volume_val=volume_val,
            ))

        if FAKE_SOURCE_PATTERN.search(source) or row_ticker.startswith(TEST_TICKER_PREFIX):
            anomalies.append(_anomaly_row(
                'suspicious_source_or_ticker',
                market=market,
                ticker=row_ticker,
                date=date,
                source=source,
                open_val=open_val,
                high_val=high_val,
                low_val=low_val,
                close_val=close_val,
                volume_val=volume_val,
            ))

        if None in (open_val, high_val, low_val, close_val):
            anomalies.append(_anomaly_row(
                'nan_ohlc',
                market=market,
                ticker=row_ticker,
                date=date,
                source=source,
                open_val=open_val,
                high_val=high_val,
                low_val=low_val,
                close_val=close_val,
                volume_val=volume_val,
            ))
            continue

        if low_val > high_val:
            anomalies.append(_anomaly_row(
                'high_lt_low',
                market=market,
                ticker=row_ticker,
                date=date,
                source=source,
                open_val=open_val,
                high_val=high_val,
                low_val=low_val,
                close_val=close_val,
                volume_val=volume_val,
            ))

        if open_val < low_val or open_val > high_val:
            anomalies.append(_anomaly_row(
                'open_outside_range',
                market=market,
                ticker=row_ticker,
                date=date,
                source=source,
                open_val=open_val,
                high_val=high_val,
                low_val=low_val,
                close_val=close_val,
                volume_val=volume_val,
            ))

        if close_val < low_val or close_val > high_val:
            anomalies.append(_anomaly_row(
                'close_outside_range',
                market=market,
                ticker=row_ticker,
                date=date,
                source=source,
                open_val=open_val,
                high_val=high_val,
                low_val=low_val,
                close_val=close_val,
                volume_val=volume_val,
            ))

        if volume_val is None or volume_val == 0:
            missing_volume += 1

        cache_key = (market, row_ticker)
        if close_val and cache_key in prev_close_by_ticker:
            prev = prev_close_by_ticker[cache_key]
            if prev > 0:
                move_pct = abs((close_val - prev) / prev) * 100.0
                if move_pct > MAX_DAILY_MOVE_PCT:
                    anomalies.append(_anomaly_row(
                        'suspicious_daily_move',
                        market=market,
                        ticker=row_ticker,
                        date=date,
                        source=source,
                        open_val=open_val,
                        high_val=high_val,
                        low_val=low_val,
                        close_val=close_val,
                        volume_val=volume_val,
                        move_pct=round(move_pct, 2),
                    ))
                if exclude_scale_discontinuity and close_val > 0:
                    ratio = close_val / prev
                    if ratio > SCALE_DISCONTINUITY_RATIO_HIGH or ratio < SCALE_DISCONTINUITY_RATIO_LOW:
                        anomalies.append(_anomaly_row(
                            'scale_discontinuity',
                            market=market,
                            ticker=row_ticker,
                            date=date,
                            source=source,
                            open_val=open_val,
                            high_val=high_val,
                            low_val=low_val,
                            close_val=close_val,
                            volume_val=volume_val,
                            prev_close=prev,
                            close_ratio=round(ratio, 4),
                        ))
        if close_val:
            prev_close_by_ticker[cache_key] = close_val

    return {
        'rows': len(rows),
        'tickers': len(tickers),
        'anomalies': len(anomalies),
        'anomaly_details': anomalies,
        'missing_volume_warned': missing_volume,
        'fake_prices': fake_prices,
        'ok': fake_prices == 0,
    }


def audit_and_build_anomaly_records(
    *,
    ticker: str | None = None,
    exclude_scale_discontinuity: bool = False,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Run audit and build DB-ready anomaly quarantine rows."""
    from datetime import datetime, timezone

    from backend.storage.historical_market_store import make_anomaly_id

    audit = audit_historical_prices(
        ticker=ticker,
        exclude_scale_discontinuity=exclude_scale_discontinuity,
    )
    detected_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    records: list[dict[str, Any]] = []

    for item in audit.get('anomaly_details') or []:
        market = str(item.get('market') or '').strip().upper()
        row_ticker = str(item.get('ticker') or '').strip().upper()
        date = str(item.get('date') or '')
        reason = str(item.get('reason') or item.get('type') or '')
        source = str(item.get('source') or '')
        severity = item.get('severity') or severity_for_reason(reason)
        records.append({
            'anomaly_id': make_anomaly_id(market, row_ticker, date, reason, source),
            'market': market,
            'ticker': row_ticker,
            'date': date,
            'reason': reason,
            'severity': severity,
            'open': item.get('open'),
            'high': item.get('high'),
            'low': item.get('low'),
            'close': item.get('close'),
            'volume': item.get('volume'),
            'source': source,
            'detected_at': detected_at,
            'status': 'active',
            'notes': None,
        })

    return audit, records
