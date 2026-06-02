#!/usr/bin/env python3
"""
Smoke test for live market memory prediction capture.

Usage:
  python scripts/test_market_memory_capture.py

Prints exactly MARKET_MEMORY_CAPTURE_OK on success; exits 1 on failure.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if str(Path.cwd().resolve()) != str(PROJECT_ROOT.resolve()):
    import os

    os.chdir(PROJECT_ROOT)

TEST_TICKER = '__TEST_CAPTURE__'
TEST_TS = '2026-01-01T00:00:00+00:00'


def _fail(msg: str) -> int:
    print(f'MARKET_MEMORY_CAPTURE_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.storage.market_memory_capture import capture_prediction
    from backend.storage.market_memory_db import get_connection, init_market_memory_db

    if not init_market_memory_db():
        return _fail('init_market_memory_db returned False')

    prediction_id = capture_prediction(
        {
            'ticker': TEST_TICKER,
            'timestamp': TEST_TS,
            'source': 'test',
            'direction': 'BUY',
            'confidence': 'HIGH',
            'reasoning': 'smoke test',
        },
        source_hint='test',
    )
    if not prediction_id:
        return _fail('capture_prediction returned None')

    conn = get_connection()
    try:
        row = conn.execute(
            """
            SELECT prediction_id, ticker, timestamp, source, direction, confidence_label
            FROM predictions
            WHERE ticker = ?
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            (TEST_TICKER,),
        ).fetchone()
        if row is None:
            return _fail('test row not found in predictions table')
        if row['ticker'] != TEST_TICKER:
            return _fail(f'unexpected ticker: {row["ticker"]}')
        if row['source'] != 'test':
            return _fail(f'unexpected source: {row["source"]}')

        conn.execute('DELETE FROM predictions WHERE ticker = ?', (TEST_TICKER,))
        conn.commit()
    finally:
        conn.close()

    print('MARKET_MEMORY_CAPTURE_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
