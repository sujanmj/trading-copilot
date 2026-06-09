#!/usr/bin/env python3
"""Unit tests — reference price backfill apply idempotency (Stage 49C)."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

TEST_TICKER = '__TEST_BACKFILL_APPLY__'


def _fail(msg: str) -> int:
    print(f'REFERENCE_PRICE_BACKFILL_APPLY_IDEMPOTENT_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.storage.market_memory_db import get_connection, init_market_memory_db, upsert_prediction
    from backend.storage.outcome_price_lookup import PriceHit, backfill_prediction_reference_prices

    if not init_market_memory_db():
        return _fail('init_market_memory_db failed')

    old_ts = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    pid = upsert_prediction({
        'ticker': TEST_TICKER,
        'timestamp': old_ts,
        'source': 'backfill_apply_test',
        'direction': 'BULLISH',
        'raw_payload': {'signal_time': old_ts, 'horizon': 'next_day'},
    })
    if not pid:
        return _fail('upsert_prediction failed')

    hit = PriceHit(77.25, 'scanner_data', datetime.now(timezone.utc))
    conn = get_connection()
    try:
        row = conn.execute('SELECT * FROM predictions WHERE prediction_id = ?', (pid,)).fetchone()
        pending = [dict(row)]
        with patch('backend.storage.outcome_resolver.get_pending_predictions') as mock_pending:
            def _pending(limit: int = 500) -> list[dict]:
                row = conn.execute('SELECT * FROM predictions WHERE prediction_id = ?', (pid,)).fetchone()
                return [dict(row)] if row else []

            mock_pending.side_effect = _pending
            with patch('backend.storage.outcome_price_lookup.lookup_reference_price', return_value=hit):
                first = backfill_prediction_reference_prices(dry_run=False, limit=20)
                second = backfill_prediction_reference_prices(dry_run=False, limit=20)
        if int(first.get('updated') or 0) != 1:
            return _fail(f'first apply expected updated=1 got {first!r}')
        if int(second.get('updated') or 0) != 0:
            return _fail(f'second apply must be idempotent got {second!r}')
        row = conn.execute('SELECT raw_payload FROM predictions WHERE prediction_id = ?', (pid,)).fetchone()
        raw = json.loads(row['raw_payload']) if row else {}
        if float(raw.get('reference_price') or 0) != 77.25:
            return _fail(f'expected reference_price=77.25 got {raw!r}')
    finally:
        conn.execute('DELETE FROM predictions WHERE prediction_id = ?', (pid,))
        conn.commit()
        conn.close()

    print('REFERENCE_PRICE_BACKFILL_APPLY_IDEMPOTENT_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
