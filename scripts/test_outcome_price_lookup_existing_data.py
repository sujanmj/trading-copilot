#!/usr/bin/env python3
"""Unit tests — outcome price lookup from existing stored data (Stage 49C)."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

TEST_TICKER = '__TEST_PRICE_LOOKUP__'


def _fail(msg: str) -> int:
    print(f'OUTCOME_PRICE_LOOKUP_EXISTING_DATA_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.storage.outcome_price_lookup import OutcomePriceStore, lookup_reference_price

    signal_time = datetime(2026, 5, 20, 10, 0, tzinfo=timezone.utc)
    scan_time = datetime(2026, 5, 20, 9, 30, tzinfo=timezone.utc)
    store = OutcomePriceStore()
    store._loaded = True
    store.scanner_prices = {TEST_TICKER: [(scan_time, 123.45)]}

    prediction = {
        'prediction_id': 'mm:test_price_lookup',
        'ticker': TEST_TICKER,
        'timestamp': signal_time.isoformat(),
        'raw_payload': {'horizon': 'next_day'},
    }
    hit = lookup_reference_price(prediction, signal_time, store)
    if hit is None or abs(hit.price - 123.45) > 0.001:
        return _fail(f'expected scanner reference price got {hit!r}')
    if hit.source != 'scanner_data':
        return _fail(f'expected scanner_data source got {hit.source!r}')

    print('OUTCOME_PRICE_LOOKUP_EXISTING_DATA_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
