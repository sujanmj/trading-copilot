#!/usr/bin/env python3
"""
Unit tests for historical anomaly quarantine (temp DB, no network).

Usage:
  python scripts/test_historical_anomaly_quarantine.py

Prints HISTORICAL_ANOMALY_QUARANTINE_TEST_OK on success.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if str(Path.cwd().resolve()) != str(PROJECT_ROOT.resolve()):
    import os

    os.chdir(PROJECT_ROOT)

TEST_TICKER = 'ANOMALYQTEST'


def _fail(msg: str) -> int:
    print(f'HISTORICAL_ANOMALY_QUARANTINE_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def _run_tests(db_path: Path) -> str | None:
    from backend.analytics.historical_price_audit import (
        audit_and_build_anomaly_records,
        severity_for_reason,
    )
    from backend.storage.historical_market_store import (
        get_active_anomalies,
        get_excluded_simulation_dates,
        get_prices,
        init_db,
        upsert_price_anomalies,
        upsert_prices,
    )
    from backend.storage.historical_outcome_replay import (
        _apply_anomaly_warnings,
        _load_replay_candles,
        resolve_replay_from_candles,
    )

    if not init_db():
        return 'init_db failed'

    upsert_prices([
        {
            'market': 'INDIA',
            'ticker': TEST_TICKER,
            'date': '2026-01-01',
            'source': 'validate',
            'open': 100.0,
            'high': 102.0,
            'low': 99.0,
            'close': 101.0,
            'volume': 1000.0,
            'fake_prices': 0,
        },
        {
            'market': 'INDIA',
            'ticker': TEST_TICKER,
            'date': '2026-01-02',
            'source': 'validate',
            'open': 101.0,
            'high': 150.0,
            'low': 100.0,
            'close': 145.0,
            'volume': 2000.0,
            'fake_prices': 0,
        },
        {
            'market': 'INDIA',
            'ticker': TEST_TICKER,
            'date': '2026-01-03',
            'source': 'validate',
            'open': 0.28,
            'high': 0.31,
            'low': 0.27,
            'close': 0.30,
            'volume': 3000.0,
            'fake_prices': 0,
        },
        {
            'market': 'INDIA',
            'ticker': TEST_TICKER,
            'date': '2026-01-04',
            'source': 'validate',
            'open': 32.0,
            'high': 35.0,
            'low': 31.0,
            'close': 33.0,
            'volume': 4000.0,
            'fake_prices': 0,
        },
        {
            'market': 'INDIA',
            'ticker': TEST_TICKER,
            'date': '2026-01-05',
            'source': 'validate',
            'open': 50.0,
            'high': 40.0,
            'low': 55.0,
            'close': 45.0,
            'volume': 5000.0,
            'fake_prices': 0,
        },
    ])

    audit, records = audit_and_build_anomaly_records(
        ticker=TEST_TICKER,
        exclude_scale_discontinuity=True,
    )
    reasons = {item.get('reason') for item in audit.get('anomaly_details') or []}

    if 'suspicious_daily_move' not in reasons:
        return 'expected suspicious_daily_move for big plausible move'
    if 'scale_discontinuity' not in reasons:
        return 'expected scale_discontinuity for 0.30->33 jump'
    if 'high_lt_low' not in reasons:
        return 'expected high_lt_low for impossible OHLC'

    if severity_for_reason('suspicious_daily_move') != 'warning':
        return 'suspicious_daily_move severity must be warning'
    if severity_for_reason('scale_discontinuity') != 'exclude_from_simulation':
        return 'scale_discontinuity severity must be exclude_from_simulation'
    if severity_for_reason('high_lt_low') != 'exclude_from_simulation':
        return 'high_lt_low severity must be exclude_from_simulation'

    normal_rows = get_prices(ticker=TEST_TICKER, market='INDIA', from_date='2026-01-01', to_date='2026-01-01')
    if len(normal_rows) != 1:
        return f'expected 1 normal candle row, got {len(normal_rows)}'

    written = upsert_price_anomalies(records)
    if written < 3:
        return f'expected at least 3 anomaly records written, got {written}'

    excluded = get_excluded_simulation_dates('INDIA', TEST_TICKER)
    if '2026-01-04' not in excluded:
        return 'scale discontinuity date must be excluded from simulation'
    if '2026-01-05' not in excluded:
        return 'high_lt_low date must be excluded from simulation'

    candles, _, warning_dates = _load_replay_candles(market='INDIA', ticker=TEST_TICKER)
    candle_dates = {c['date'] for c in candles}
    if '2026-01-04' in candle_dates or '2026-01-05' in candle_dates:
        return 'excluded anomaly dates must not appear in replay candles'
    if '2026-01-02' not in candle_dates:
        return 'warning-only date should remain in replay candles'

    replay = resolve_replay_from_candles({
        'prediction_id': 'mm:test_anomaly_q',
        'ticker': TEST_TICKER,
        'timestamp': '2026-01-02T00:00:00+00:00',
        'direction': 'BULLISH',
        'raw_payload': {
            'entry_price': 101.0,
            'target_price': 140.0,
            'stop_loss': 95.0,
        },
    }, candles, market='INDIA')
    if not replay:
        return 'expected replay resolution on warning-only candle'

    replay = _apply_anomaly_warnings(replay, warning_dates)
    raw_payload = replay.get('raw_payload') or {}
    if not raw_payload.get('historical_anomaly_warning'):
        return 'expected historical_anomaly_warning on warning-only replay date'

    active = get_active_anomalies(ticker=TEST_TICKER)
    if len(active) < 3:
        return f'expected at least 3 active anomalies, got {len(active)}'

    return None


def main() -> int:
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / 'test_historical_market_memory.db'

        def _patched_path() -> Path:
            return db_path

        with patch(
            'backend.storage.historical_market_store.get_historical_db_path',
            _patched_path,
        ):
            err = _run_tests(db_path)

    if err:
        return _fail(err)

    print('HISTORICAL_ANOMALY_QUARANTINE_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
