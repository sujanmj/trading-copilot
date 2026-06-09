#!/usr/bin/env python3
"""Unit tests — no fake outcomes without evaluation price (Stage 49C safety)."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

TEST_TICKER = '__TEST_RESOLVER_NO_PRICE__'


def _fail(msg: str) -> int:
    print(f'OUTCOME_RESOLVER_NO_FAKE_WITHOUT_PRICE_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.storage.market_memory_db import get_connection, init_market_memory_db, upsert_prediction
    from backend.storage.outcome_price_lookup import OutcomePriceStore, PriceHit, validate_resolution_price_pair
    from backend.storage.outcome_resolver import resolve_single_prediction, run_outcome_resolver_once

    if not init_market_memory_db():
        return _fail('init_market_memory_db failed')

    old_ts = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
    signal_time = datetime.fromisoformat(old_ts)
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

    empty_store = OutcomePriceStore()
    empty_store._loaded = True

    conn = get_connection()
    try:
        row = conn.execute('SELECT * FROM predictions WHERE prediction_id = ?', (pid,)).fetchone()
        prediction = dict(row)
        pending = [prediction]

        payload, skip = resolve_single_prediction(
            prediction,
            {'prices': {}},
            store=empty_store,
        )
        if payload is not None or skip != 'missing_evaluation_price':
            return _fail(f'resolve_single_prediction must skip missing eval got skip={skip!r} payload={payload!r}')

        ref_hit = PriceHit(80.0, 'prediction_payload', signal_time)
        same_ts_eval = PriceHit(80.0, 'scanner_data', signal_time)
        if validate_resolution_price_pair(ref_hit, same_ts_eval, signal_time, 18.0):
            return _fail('same timestamp evaluation must be rejected')

        with patch('backend.storage.outcome_resolver.get_pending_predictions', return_value=pending):
            summary = run_outcome_resolver_once(
                limit=5,
                market_data={'prices': {}},
                refresh_cache=False,
            )
        if int(summary.get('resolved_new') or 0) != 0:
            return _fail(f'must not resolve without evaluation price got {summary!r}')
        if int(summary.get('skipped_missing_evaluation') or 0) != 1:
            return _fail(f'expected skipped_missing_evaluation=1 got {summary!r}')

        outcome_row = conn.execute(
            'SELECT 1 FROM outcomes WHERE prediction_id = ? AND holding_period = ?',
            (pid, 'signal_quality'),
        ).fetchone()
        if outcome_row is not None:
            return _fail('must not write outcome row without evaluation price')
    finally:
        conn.execute('DELETE FROM outcomes WHERE prediction_id = ?', (pid,))
        conn.execute('DELETE FROM predictions WHERE prediction_id = ?', (pid,))
        conn.commit()
        conn.close()

    print('OUTCOME_RESOLVER_NO_FAKE_WITHOUT_PRICE_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
