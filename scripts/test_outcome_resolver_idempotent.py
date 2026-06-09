#!/usr/bin/env python3
"""Unit tests — outcome resolver idempotency (Stage 49A)."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

TEST_TICKER = '__TEST_RESOLVER_IDEM__'


def _fail(msg: str) -> int:
    print(f'OUTCOME_RESOLVER_IDEMPOTENT_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.storage.outcome_price_lookup import PriceHit
    from backend.storage.market_memory_db import get_connection, init_market_memory_db, upsert_prediction
    from backend.storage.outcome_resolver import run_outcome_resolver_once

    if not init_market_memory_db():
        return _fail('init_market_memory_db failed')

    old_ts = (datetime.now(timezone.utc) - timedelta(days=4)).isoformat()
    pid = upsert_prediction({
        'ticker': TEST_TICKER,
        'timestamp': old_ts,
        'source': 'resolver_idem_test',
        'direction': 'BULLISH',
        'raw_payload': {
            'entry_price': 50.0,
            'signal_time': old_ts,
            'horizon': 'next_day',
            'signal_type': 'WATCH',
        },
    })
    if not pid:
        return _fail('upsert_prediction failed')

    market_data = {
        'last_updated': datetime.now(timezone.utc).isoformat(),
        'prices': {TEST_TICKER: {'price': 51.0}},
    }
    conn = get_connection()
    try:
        row = conn.execute('SELECT * FROM predictions WHERE prediction_id = ?', (pid,)).fetchone()
        pending = [dict(row)]
        eval_hit = PriceHit(51.0, 'latest_market_data', datetime.now(timezone.utc))
        with patch(
            'backend.storage.outcome_resolver.get_pending_predictions',
            return_value=pending,
        ):
            with patch('backend.storage.outcome_price_lookup.lookup_evaluation_price', return_value=eval_hit):
                first = run_outcome_resolver_once(limit=20, market_data=market_data, refresh_cache=False)
                if int(first.get('resolved_new') or 0) != 1:
                    return _fail(f'first run expected resolved_new=1 got {first!r}')

                second = run_outcome_resolver_once(limit=20, market_data=market_data, refresh_cache=False)
        if int(second.get('resolved_new') or 0) != 0:
            return _fail(f'second run must be idempotent got {second!r}')
    finally:
        conn.execute('DELETE FROM outcomes WHERE prediction_id = ?', (pid,))
        conn.execute('DELETE FROM predictions WHERE prediction_id = ?', (pid,))
        conn.commit()
        conn.close()

    print('OUTCOME_RESOLVER_IDEMPOTENT_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
