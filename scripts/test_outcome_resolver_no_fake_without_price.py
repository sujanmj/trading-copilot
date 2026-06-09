#!/usr/bin/env python3
"""Unit tests — no fake outcomes without price data (Stage 49A)."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

TEST_TICKER = '__TEST_RESOLVER_NO_PRICE__'


def _fail(msg: str) -> int:
    print(f'OUTCOME_RESOLVER_NO_FAKE_WITHOUT_PRICE_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.storage.market_memory_db import get_connection, init_market_memory_db, upsert_prediction
    from backend.storage.outcome_resolver import run_outcome_resolver_once

    if not init_market_memory_db():
        return _fail('init_market_memory_db failed')

    old_ts = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
    pid = upsert_prediction({
        'ticker': TEST_TICKER,
        'timestamp': old_ts,
        'source': 'resolver_no_price_test',
        'direction': 'BULLISH',
        'raw_payload': {
            'entry_price': 80.0,
            'signal_time': old_ts,
            'horizon': 'next_day',
        },
    })
    if not pid:
        return _fail('upsert_prediction failed')

    conn = get_connection()
    try:
        summary = run_outcome_resolver_once(
            limit=20,
            market_data={'prices': {}},
            refresh_cache=False,
        )
        if int(summary.get('resolved_new') or 0) != 0:
            return _fail('must not resolve without evaluation price')

        row = conn.execute(
            'SELECT 1 FROM outcomes WHERE prediction_id = ? AND holding_period = ?',
            (pid, 'signal_quality'),
        ).fetchone()
        if row is not None:
            return _fail('must not write outcome row without price data')
    finally:
        conn.execute('DELETE FROM predictions WHERE prediction_id = ?', (pid,))
        conn.commit()
        conn.close()

    print('OUTCOME_RESOLVER_NO_FAKE_WITHOUT_PRICE_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
