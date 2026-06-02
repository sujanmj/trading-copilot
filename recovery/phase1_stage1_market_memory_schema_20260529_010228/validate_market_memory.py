#!/usr/bin/env python3
"""
Validate canonical market memory DB schema and smoke-test upserts.

Usage:
  python scripts/validate_market_memory.py

Prints exactly MARKET_MEMORY_OK on success; exits 1 on failure.
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

TABLES = (
    'predictions',
    'broker_predictions',
    'outcomes',
    'market_context_snapshots',
)

EXPECTED_INDEXES = (
    'idx_mm_predictions_ticker',
    'idx_mm_predictions_timestamp',
    'idx_mm_predictions_source',
    'idx_mm_predictions_direction',
    'idx_mm_predictions_market_regime',
    'idx_mm_predictions_sector',
    'idx_mm_broker_ticker',
    'idx_mm_broker_source',
    'idx_mm_broker_direction',
    'idx_mm_broker_timeframe',
    'idx_mm_outcomes_prediction_id',
    'idx_mm_outcomes_resolved_as',
    'idx_mm_outcomes_market_regime',
    'idx_mm_outcomes_holding_period',
    'idx_mm_context_timestamp',
    'idx_mm_context_market_regime',
)

TEST_TICKER = '__TEST__'


def _fail(msg: str) -> int:
    print(f'MARKET_MEMORY_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.storage.market_memory_db import (
        get_connection,
        get_market_memory_path,
        get_market_memory_stats,
        init_market_memory_db,
        insert_market_context_snapshot,
        upsert_broker_prediction,
        upsert_outcome,
        upsert_prediction,
    )

    if not init_market_memory_db():
        return _fail('init_market_memory_db returned False')

    db_path = get_market_memory_path()
    if not db_path.exists():
        return _fail(f'database missing: {db_path}')

    conn = get_connection()
    try:
        existing_tables = {
            row['name']
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        for table in TABLES:
            if table not in existing_tables:
                return _fail(f'missing table: {table}')

        existing_indexes = {
            row['name']
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            ).fetchall()
        }
        for index_name in EXPECTED_INDEXES:
            if index_name not in existing_indexes:
                return _fail(f'missing index: {index_name}')

        for table in TABLES:
            row = conn.execute(f'SELECT COUNT(*) AS cnt FROM {table}').fetchone()
            if row is None:
                return _fail(f'COUNT(*) failed for {table}')
    finally:
        conn.close()

    stats = get_market_memory_stats()
    required_keys = (
        'predictions',
        'broker_predictions',
        'outcomes',
        'market_context_snapshots',
        'db_path',
        'db_exists',
    )
    for key in required_keys:
        if key not in stats:
            return _fail(f'stats missing key: {key}')
    if not stats.get('db_exists'):
        return _fail('stats.db_exists is False')

    test_ts = '2026-05-29T00:00:00+00:00'
    prediction_id = upsert_prediction({
        'ticker': TEST_TICKER,
        'timestamp': test_ts,
        'source': 'validate',
        'direction': 'BUY',
        'reasoning': 'smoke test',
    })
    if not prediction_id:
        return _fail('upsert_prediction smoke test failed')

    broker_id = upsert_broker_prediction({
        'prediction_id': prediction_id,
        'broker_source': 'validate',
        'ticker': TEST_TICKER,
        'bullish_or_bearish': 'BULLISH',
        'target_type': 'price',
        'timeframe': '1d',
    })
    if broker_id is None:
        return _fail('upsert_broker_prediction smoke test failed')

    if not upsert_outcome({
        'prediction_id': prediction_id,
        'holding_period': '1d',
        'resolved_as': 'PENDING',
    }):
        return _fail('upsert_outcome smoke test failed')

    context_id = insert_market_context_snapshot({
        'timestamp': test_ts,
        'market_regime': 'validate',
        'vix': 12.5,
    })
    if not context_id:
        return _fail('insert_market_context_snapshot smoke test failed')

    cleanup_conn = get_connection()
    try:
        cleanup_conn.execute('DELETE FROM outcomes WHERE prediction_id = ?', (prediction_id,))
        cleanup_conn.execute('DELETE FROM broker_predictions WHERE ticker = ?', (TEST_TICKER,))
        cleanup_conn.execute('DELETE FROM predictions WHERE ticker = ?', (TEST_TICKER,))
        cleanup_conn.execute(
            'DELETE FROM market_context_snapshots WHERE context_id = ?',
            (context_id,),
        )
        cleanup_conn.commit()
    finally:
        cleanup_conn.close()

    print('MARKET_MEMORY_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
