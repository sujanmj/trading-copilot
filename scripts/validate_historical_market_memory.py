#!/usr/bin/env python3
"""
Validate historical market memory DB schema and smoke-test upserts.

Usage:
  python scripts/validate_historical_market_memory.py

Prints exactly HISTORICAL_MARKET_MEMORY_OK on success; exits 1 on failure.
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
    'historical_prices',
    'historical_outcome_replay',
    'historical_source_performance',
    'historical_price_anomalies',
    'historical_simulation_runs',
    'historical_simulated_predictions',
    'historical_simulated_outcomes',
    'historical_strategy_performance',
)

EXPECTED_INDEXES = (
    'idx_hmp_market_ticker',
    'idx_hmp_date',
    'idx_hmp_ticker_date',
    'idx_hmor_prediction_id',
    'idx_hmor_ticker',
    'idx_hmor_resolved_as',
    'idx_hmor_prediction_date',
    'idx_hmor_replay_date',
    'idx_hmsp_market',
    'idx_hpa_ticker',
    'idx_hpa_date',
    'idx_hpa_severity',
    'idx_hpa_status',
    'idx_hsr_market',
    'idx_hsr_created_at',
    'idx_hsr_params_hash',
    'idx_hsp_run_id',
    'idx_hsp_ticker',
    'idx_hsp_signal_date',
    'idx_hsp_strategy',
    'idx_hsp_market',
    'idx_hso_sim_prediction_id',
    'idx_hso_ticker',
    'idx_hso_result',
    'idx_hso_strategy',
    'idx_hstrat_market',
)

TEST_TICKER = '__TEST_HIST__'


def _fail(msg: str) -> int:
    print(f'HISTORICAL_MARKET_MEMORY_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.storage.historical_market_store import (
        get_connection,
        get_historical_db_path,
        get_stats,
        init_db,
        insert_replay,
        upsert_prices,
    )

    if not init_db():
        return _fail('init_db returned False')

    db_path = get_historical_db_path()
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
    finally:
        conn.close()

    stats = get_stats()
    for key in (
        'historical_prices',
        'historical_outcome_replay',
        'historical_source_performance',
        'historical_price_anomalies',
        'historical_simulation_runs',
        'historical_simulated_predictions',
        'historical_simulated_outcomes',
        'historical_strategy_performance',
        'db_exists',
    ):
        if key not in stats:
            return _fail(f'stats missing key: {key}')
    if not stats.get('db_exists'):
        return _fail('stats.db_exists is False')

    written = upsert_prices([{
        'market': 'INDIA',
        'ticker': TEST_TICKER,
        'date': '2026-05-01',
        'source': 'validate',
        'open': 100.0,
        'high': 105.0,
        'low': 99.0,
        'close': 104.0,
        'volume': 1000.0,
        'fake_prices': 0,
    }])
    if written != 1:
        return _fail('upsert_prices smoke test failed')

    replay_id = insert_replay({
        'prediction_id': 'mm:validate_hist',
        'ticker': TEST_TICKER,
        'market': 'INDIA',
        'prediction_date': '2026-05-01',
        'direction': 'BULLISH',
        'entry_price': 100.0,
        'target_price': 105.0,
        'stop_loss': 98.0,
        'resolved_as': 'WIN',
        'expiry_result': 'TARGET_HIT_BY_HISTORICAL_CANDLE',
        'replay_date': '2026-05-02',
        'source': 'validate',
    })
    if not replay_id:
        return _fail('insert_replay smoke test failed')

    cleanup = get_connection()
    try:
        cleanup.execute('DELETE FROM historical_prices WHERE ticker = ?', (TEST_TICKER,))
        cleanup.execute('DELETE FROM historical_outcome_replay WHERE ticker = ?', (TEST_TICKER,))
        cleanup.commit()
    finally:
        cleanup.close()

    print('HISTORICAL_MARKET_MEMORY_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
