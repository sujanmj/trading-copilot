#!/usr/bin/env python3
"""
Smoke test for broker consensus engine.

Usage:
  python scripts/test_broker_consensus_engine.py

Prints exactly BROKER_CONSENSUS_OK on success; exits 1 on failure.
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

TEST_TICKER = '__TEST_CONSENSUS__'
TEST_TIMEFRAME = 'test_consensus'

TEST_PICKS = (
    {'broker_source': 'Moneycontrol', 'bullish_or_bearish': 'BULLISH', 'confidence': 0.7},
    {'broker_source': 'INDmoney', 'bullish_or_bearish': 'BULLISH', 'confidence': 0.65},
    {'broker_source': 'Groww', 'bullish_or_bearish': 'BULLISH', 'confidence': 0.6},
    {'broker_source': 'Reddit', 'bullish_or_bearish': 'BULLISH', 'confidence': 0.5},
    {'broker_source': 'Angel One', 'bullish_or_bearish': 'BEARISH', 'confidence': 0.55},
)


def _fail(msg: str) -> int:
    print(f'BROKER_CONSENSUS_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.analytics.broker_consensus_engine import (
        get_consensus_for_ticker,
        upsert_broker_pick,
    )
    from backend.storage.market_memory_db import get_connection, init_market_memory_db

    if not init_market_memory_db():
        return _fail('init_market_memory_db returned False')

    inserted_ids: list[int] = []
    for pick in TEST_PICKS:
        row_id = upsert_broker_pick({
            'broker_source': pick['broker_source'],
            'ticker': TEST_TICKER,
            'bullish_or_bearish': pick['bullish_or_bearish'],
            'confidence': pick['confidence'],
            'timeframe': TEST_TIMEFRAME,
            'target_type': 'consensus_test',
        })
        if row_id is None:
            return _fail(f'upsert_broker_pick failed for {pick["broker_source"]}')
        inserted_ids.append(row_id)

    consensus = get_consensus_for_ticker(TEST_TICKER, timeframe=TEST_TIMEFRAME)

    if consensus.get('total_sources') != 5:
        return _fail(f'expected total_sources=5, got {consensus.get("total_sources")}')
    if consensus.get('bullish_count') != 4:
        return _fail(f'expected bullish_count=4, got {consensus.get("bullish_count")}')
    if consensus.get('bearish_count') != 1:
        return _fail(f'expected bearish_count=1, got {consensus.get("bearish_count")}')
    if consensus.get('agreement_direction') != 'BULLISH':
        return _fail(
            f'expected agreement_direction=BULLISH, got {consensus.get("agreement_direction")}'
        )

    conn = get_connection()
    try:
        remaining = conn.execute(
            'SELECT COUNT(*) AS cnt FROM broker_predictions WHERE ticker = ?',
            (TEST_TICKER,),
        ).fetchone()
        if remaining is None or int(remaining['cnt']) != 5:
            return _fail('expected 5 test broker rows before cleanup')

        conn.execute(
            'DELETE FROM broker_predictions WHERE ticker = ?',
            (TEST_TICKER,),
        )
        conn.commit()

        remaining_after = conn.execute(
            'SELECT COUNT(*) AS cnt FROM broker_predictions WHERE ticker = ?',
            (TEST_TICKER,),
        ).fetchone()
        if remaining_after is None or int(remaining_after['cnt']) != 0:
            return _fail('test broker rows were not cleaned up')
    finally:
        conn.close()

    print('BROKER_CONSENSUS_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
