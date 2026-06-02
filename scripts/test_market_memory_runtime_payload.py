#!/usr/bin/env python3
"""
Smoke test for live capture of a realistic opportunity/prediction payload.

Usage:
  python scripts/test_market_memory_runtime_payload.py

Prints inserted prediction_id, then exactly MARKET_MEMORY_RUNTIME_PAYLOAD_OK on success.
Removes the test row before exit.
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

TEST_TICKER = '__TEST_RUNTIME_OPP__'
TEST_TS = '2026-01-01T00:00:00+00:00'

RUNTIME_OPPORTUNITY = {
    'ticker': TEST_TICKER,
    'recommendation': 'BUY',
    'confidence': 'HIGH',
    'score': 82,
    'current_price': 100,
    'target_price': 108,
    'stop_loss': 96,
    'sector': 'TEST',
    'market_regime': 'test_regime',
    'reasoning': 'runtime capture validation',
    'source': 'runtime_test',
    'timestamp': TEST_TS,
}


def _fail(msg: str) -> int:
    print(f'MARKET_MEMORY_RUNTIME_PAYLOAD_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.storage.market_memory_capture import capture_opportunity_as_prediction
    from backend.storage.market_memory_db import get_connection, init_market_memory_db

    if not init_market_memory_db():
        return _fail('init_market_memory_db returned False')

    prediction_id = capture_opportunity_as_prediction(
        RUNTIME_OPPORTUNITY,
        source_hint='runtime_test',
    )
    if not prediction_id:
        return _fail('capture_opportunity_as_prediction returned None')

    print(prediction_id)

    conn = get_connection()
    try:
        row = conn.execute(
            """
            SELECT prediction_id, ticker, timestamp, source, direction,
                   confidence, confidence_label, market_regime, sector, reasoning
            FROM predictions
            WHERE prediction_id = ?
            """,
            (prediction_id,),
        ).fetchone()
        if row is None:
            return _fail('test row not found in predictions table')
        if row['ticker'] != TEST_TICKER:
            return _fail(f'unexpected ticker: {row["ticker"]}')
        if row['source'] != 'runtime_test':
            return _fail(f'unexpected source: {row["source"]}')
        if row['direction'] != 'BULLISH':
            return _fail(f'unexpected direction: {row["direction"]}')
        if row['confidence_label'] != 'HIGH':
            return _fail(f'unexpected confidence_label: {row["confidence_label"]}')
        if row['market_regime'] != 'test_regime':
            return _fail(f'unexpected market_regime: {row["market_regime"]}')
        if row['sector'] != 'TEST':
            return _fail(f'unexpected sector: {row["sector"]}')
        if row['reasoning'] != 'runtime capture validation':
            return _fail(f'unexpected reasoning: {row["reasoning"]}')

        conn.execute('DELETE FROM predictions WHERE prediction_id = ?', (prediction_id,))
        conn.commit()

        gone = conn.execute(
            'SELECT 1 FROM predictions WHERE prediction_id = ?',
            (prediction_id,),
        ).fetchone()
        if gone is not None:
            return _fail('test row still present after delete')

        leftover = conn.execute(
            'SELECT 1 FROM predictions WHERE ticker = ?',
            (TEST_TICKER,),
        ).fetchone()
        if leftover is not None:
            return _fail('test ticker rows remain after delete')
    finally:
        conn.close()

    print('MARKET_MEMORY_RUNTIME_PAYLOAD_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
