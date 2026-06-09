#!/usr/bin/env python3
"""Unit tests — resolver missing_reference skip reason (Stage 49C)."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

TEST_TICKER = '__TEST_MISS_REF__'


def _fail(msg: str) -> int:
    print(f'OUTCOME_RESOLVER_MISSING_REFERENCE_REASON_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.storage.market_memory_db import get_connection, init_market_memory_db, upsert_prediction
    from backend.storage.outcome_resolver import run_outcome_resolver_once

    if not init_market_memory_db():
        return _fail('init_market_memory_db failed')

    old_ts = (datetime.now(timezone.utc) - timedelta(days=6)).isoformat()
    pid = upsert_prediction({
        'ticker': TEST_TICKER,
        'timestamp': old_ts,
        'source': 'missing_ref_test',
        'direction': 'BULLISH',
        'raw_payload': {'signal_time': old_ts, 'horizon': 'next_day'},
    })
    if not pid:
        return _fail('upsert_prediction failed')

    conn = get_connection()
    try:
        row = conn.execute('SELECT * FROM predictions WHERE prediction_id = ?', (pid,)).fetchone()
        pending = [dict(row)]
        with patch('backend.storage.outcome_resolver.get_pending_predictions', return_value=pending):
            with patch('backend.storage.outcome_price_lookup.lookup_reference_price', return_value=None):
                with patch('backend.storage.outcome_price_lookup.OutcomePriceStore.load') as mock_store:
                    mock_store.return_value = object()
                    summary = run_outcome_resolver_once(
                        limit=5,
                        market_data={'prices': {TEST_TICKER: {'price': 100.0}}},
                        refresh_cache=False,
                    )
        if int(summary.get('skipped_missing_reference') or 0) != 1:
            return _fail(f'expected skipped_missing_reference=1 got {summary!r}')
        if int(summary.get('resolved_new') or 0) != 0:
            return _fail('must not resolve without reference price')
    finally:
        conn.execute('DELETE FROM predictions WHERE prediction_id = ?', (pid,))
        conn.commit()
        conn.close()

    print('OUTCOME_RESOLVER_MISSING_REFERENCE_REASON_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
