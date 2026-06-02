#!/usr/bin/env python3
"""
Smoke test for market memory outcome resolver.

Usage:
  python scripts/test_market_memory_outcome_resolver.py

Prints exactly MARKET_MEMORY_OUTCOME_OK on success; exits 1 on failure.
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

TEST_TICKER = '__TEST_OUTCOME__'
TEST_TS = '2026-01-01T00:00:00+00:00'
TEST_HOLDING = 'test'


def _fail(msg: str) -> int:
    print(f'MARKET_MEMORY_OUTCOME_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.storage.market_memory_db import get_connection, init_market_memory_db, upsert_prediction
    from backend.storage.market_memory_outcomes import (
        build_outcome_payload,
        resolve_prediction_outcome,
    )

    if not init_market_memory_db():
        return _fail('init_market_memory_db returned False')

    prediction_id = upsert_prediction({
        'ticker': TEST_TICKER,
        'timestamp': TEST_TS,
        'source': 'outcome_test',
        'direction': 'BULLISH',
        'confidence': 0.8,
        'reasoning': 'outcome resolver smoke test',
    })
    if not prediction_id:
        return _fail('upsert_prediction returned None')

    prediction = {
        'prediction_id': prediction_id,
        'ticker': TEST_TICKER,
        'timestamp': TEST_TS,
        'source': 'outcome_test',
        'direction': 'BULLISH',
    }
    price_context = {
        'actual_move': 5.5,
        'high': 7.2,
        'low': -1.1,
        'resolved_as': 'WIN',
        'expiry_result': 'TARGET_HIT',
        'holding_period': TEST_HOLDING,
        'market_regime': 'test_regime',
    }
    outcome_payload = build_outcome_payload(
        prediction,
        price_context=price_context,
        holding_period=TEST_HOLDING,
    )
    if not resolve_prediction_outcome(prediction_id, outcome_payload):
        return _fail('resolve_prediction_outcome returned False')

    conn = get_connection()
    try:
        row = conn.execute(
            """
            SELECT prediction_id, holding_period, resolved_as, expiry_result, actual_move
            FROM outcomes
            WHERE prediction_id = ? AND holding_period = ?
            """,
            (prediction_id, TEST_HOLDING),
        ).fetchone()
        if row is None:
            return _fail('outcome row not found')
        if row['resolved_as'] != 'WIN':
            return _fail(f'unexpected resolved_as: {row["resolved_as"]}')
        if row['expiry_result'] != 'TARGET_HIT':
            return _fail(f'unexpected expiry_result: {row["expiry_result"]}')
        if float(row['actual_move']) != 5.5:
            return _fail(f'unexpected actual_move: {row["actual_move"]}')

        conn.execute(
            'DELETE FROM outcomes WHERE prediction_id = ? AND holding_period = ?',
            (prediction_id, TEST_HOLDING),
        )
        conn.execute('DELETE FROM predictions WHERE prediction_id = ?', (prediction_id,))
        conn.commit()
    finally:
        conn.close()

    print('MARKET_MEMORY_OUTCOME_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
