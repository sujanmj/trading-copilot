#!/usr/bin/env python3
"""Unit tests — reference price backfill dry-run (Stage 49C)."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

TEST_TICKER = '__TEST_BACKFILL_DRY__'


def _fail(msg: str) -> int:
    print(f'REFERENCE_PRICE_BACKFILL_DRY_RUN_TEST_FAIL: {msg}', file=sys.stderr)
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
        'source': 'backfill_dry_test',
        'direction': 'BULLISH',
        'raw_payload': {'signal_time': old_ts, 'horizon': 'next_day'},
    })
    if not pid:
        return _fail('upsert_prediction failed')

    hit = PriceHit(88.5, 'scanner_data', datetime.now(timezone.utc))
    conn = get_connection()
    try:
        row = conn.execute('SELECT * FROM predictions WHERE prediction_id = ?', (pid,)).fetchone()
        pending = [dict(row)]
        with patch('backend.storage.outcome_resolver.get_pending_predictions', return_value=pending):
            with patch('backend.storage.outcome_price_lookup.lookup_reference_price', return_value=hit):
                summary = backfill_prediction_reference_prices(dry_run=True, limit=20)
        if int(summary.get('candidates') or 0) < 1:
            return _fail(f'expected candidates >= 1 got {summary!r}')
        if int(summary.get('updated') or 0) != 0:
            return _fail('dry-run must not update rows')
        row = conn.execute('SELECT raw_payload FROM predictions WHERE prediction_id = ?', (pid,)).fetchone()
        raw = json.loads(row['raw_payload']) if row else {}
        if raw.get('reference_price') is not None:
            return _fail('dry-run must not write reference_price')
    finally:
        conn.execute('DELETE FROM predictions WHERE prediction_id = ?', (pid,))
        conn.commit()
        conn.close()

    print('REFERENCE_PRICE_BACKFILL_DRY_RUN_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
