#!/usr/bin/env python3
"""
Smoke test for broker consensus enrichment during market memory capture.

Usage:
  python scripts/test_market_memory_capture_with_consensus.py

Prints exactly MARKET_MEMORY_CAPTURE_CONSENSUS_OK on success; exits 1 on failure.
Removes test prediction and broker rows before exit.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if str(Path.cwd().resolve()) != str(PROJECT_ROOT.resolve()):
    import os

    os.chdir(PROJECT_ROOT)

TEST_TICKER = '__TEST_CAPTURE_CONSENSUS__'
TEST_TS = '2026-01-01T00:00:00+00:00'

TEST_BROKER_PICKS = (
    {'broker_source': 'Moneycontrol', 'bullish_or_bearish': 'BULLISH', 'confidence': 0.7},
    {'broker_source': 'INDmoney', 'bullish_or_bearish': 'BULLISH', 'confidence': 0.6},
    {'broker_source': 'Angel One', 'bullish_or_bearish': 'BEARISH', 'confidence': 0.5},
)

TEST_PREDICTION = {
    'ticker': TEST_TICKER,
    'recommendation': 'BUY',
    'confidence': 'HIGH',
    'reasoning': 'consensus enrichment test',
    'timestamp': TEST_TS,
    'source': 'consensus_capture_test',
}


def _fail(msg: str) -> int:
    print(f'MARKET_MEMORY_CAPTURE_CONSENSUS_FAIL: {msg}', file=sys.stderr)
    return 1


def _parse_signal_stack(value) -> dict | None:
    if value is None:
        return None
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return None
        return parsed if isinstance(parsed, dict) else None
    return None


def main() -> int:
    from backend.analytics.broker_consensus_engine import upsert_broker_pick
    from backend.storage.market_memory_capture import capture_prediction
    from backend.storage.market_memory_db import get_connection, init_market_memory_db

    if not init_market_memory_db():
        return _fail('init_market_memory_db returned False')

    for pick in TEST_BROKER_PICKS:
        row_id = upsert_broker_pick({
            'broker_source': pick['broker_source'],
            'ticker': TEST_TICKER,
            'bullish_or_bearish': pick['bullish_or_bearish'],
            'confidence': pick['confidence'],
            'target_type': 'consensus_capture_test',
        })
        if row_id is None:
            return _fail(f'upsert_broker_pick failed for {pick["broker_source"]}')

    prediction_id = capture_prediction(TEST_PREDICTION)
    if not prediction_id:
        return _fail('capture_prediction returned None')

    conn = get_connection()
    try:
        row = conn.execute(
            """
            SELECT prediction_id, ticker, signal_stack
            FROM predictions
            WHERE prediction_id = ?
            """,
            (prediction_id,),
        ).fetchone()
        if row is None:
            return _fail('test prediction not found in predictions table')

        signal_stack = _parse_signal_stack(row['signal_stack'])
        if signal_stack is None:
            return _fail('signal_stack missing or not parseable')

        consensus = signal_stack.get('broker_consensus')
        if not isinstance(consensus, dict):
            return _fail('broker_consensus missing from signal_stack')

        if consensus.get('total_sources') != 3:
            return _fail(
                f'expected total_sources=3, got {consensus.get("total_sources")}'
            )
        if consensus.get('bullish_count') != 2:
            return _fail(
                f'expected bullish_count=2, got {consensus.get("bullish_count")}'
            )
        if consensus.get('bearish_count') != 1:
            return _fail(
                f'expected bearish_count=1, got {consensus.get("bearish_count")}'
            )
        if consensus.get('agreement_direction') != 'BULLISH':
            return _fail(
                'expected agreement_direction=BULLISH, '
                f'got {consensus.get("agreement_direction")}'
            )

        conn.execute('DELETE FROM predictions WHERE prediction_id = ?', (prediction_id,))
        conn.execute('DELETE FROM broker_predictions WHERE ticker = ?', (TEST_TICKER,))
        conn.commit()

        pred_left = conn.execute(
            'SELECT 1 FROM predictions WHERE prediction_id = ?',
            (prediction_id,),
        ).fetchone()
        if pred_left is not None:
            return _fail('test prediction still present after delete')

        broker_left = conn.execute(
            'SELECT 1 FROM broker_predictions WHERE ticker = ?',
            (TEST_TICKER,),
        ).fetchone()
        if broker_left is not None:
            return _fail('test broker rows still present after delete')
    finally:
        conn.close()

    print('MARKET_MEMORY_CAPTURE_CONSENSUS_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
