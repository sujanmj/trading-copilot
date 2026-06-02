#!/usr/bin/env python3
"""
Validate historical simulation schema and helper functions.

Usage:
  python scripts/validate_historical_simulation.py

Prints exactly HISTORICAL_SIMULATION_VALIDATE_OK on success.
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

SIM_TABLES = (
    'historical_simulation_runs',
    'historical_simulated_predictions',
    'historical_simulated_outcomes',
    'historical_strategy_performance',
)


def _fail(msg: str) -> int:
    print(f'HISTORICAL_SIMULATION_VALIDATE_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.analytics.historical_prediction_simulator import (
        ALL_STRATEGIES,
        get_simulation_dashboard,
        resolve_sim_outcome,
    )
    from backend.storage.historical_market_store import (
        get_connection,
        get_simulation_stats,
        init_db,
        insert_run,
        list_runs,
        make_sim_outcome_id,
        make_sim_prediction_id,
        upsert_sim_outcomes,
        upsert_sim_predictions,
        upsert_strategy_performance,
    )

    if not init_db():
        return _fail('init_db returned False')

    conn = get_connection()
    try:
        existing = {
            row['name']
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        for table in SIM_TABLES:
            if table not in existing:
                return _fail(f'missing table: {table}')
    finally:
        conn.close()

    if len(ALL_STRATEGIES) != 3:
        return _fail('expected 3 strategies')

    test_run = '__TEST_SIM_RUN__'
    test_pred_id = make_sim_prediction_id(test_run, 'INDIA', '__TEST_SIM__', '2026-01-15', 'momentum_breakout_20')
    if not test_pred_id or test_pred_id == '0':
        return _fail('make_sim_prediction_id failed')

    pred = {
        'sim_prediction_id': test_pred_id,
        'run_id': test_run,
        'market': 'INDIA',
        'ticker': '__TEST_SIM__',
        'signal_date': '2026-01-15',
        'strategy': 'momentum_breakout_20',
        'direction': 'BULLISH',
        'entry_price': 100.0,
        'target_price': 105.0,
        'stop_loss': 97.0,
        'horizon': 'swing_5d',
    }
    candles = [
        {'date': '2026-01-15', 'open': 100, 'high': 101, 'low': 99, 'close': 100, 'volume': 1, 'fake_prices': 0},
        {'date': '2026-01-16', 'open': 100, 'high': 106, 'low': 99, 'close': 105, 'volume': 1, 'fake_prices': 0},
    ]
    outcome = resolve_sim_outcome(pred, candles)
    if not outcome or outcome.get('result') != 'WIN':
        return _fail('resolve_sim_outcome smoke test failed')

    if not insert_run({
        'run_id': test_run,
        'strategy_set': 'momentum_breakout_20',
        'market': 'INDIA',
        'from_date': '2026-01-01',
        'to_date': '2026-01-31',
        'tickers': 1,
        'generated_predictions': 1,
        'resolved_predictions': 1,
        'wins': 1,
        'losses': 0,
        'ambiguous': 0,
        'params_json': {'test': True},
    }):
        return _fail('insert_run failed')

    if upsert_sim_predictions([{**pred, 'confidence': 0.6, 'features_json': {'simulation': True}}]) != 1:
        return _fail('upsert_sim_predictions failed')

    outcome_row = {
        **outcome,
        'sim_outcome_id': make_sim_outcome_id(test_pred_id),
    }
    if upsert_sim_outcomes([outcome_row]) != 1:
        return _fail('upsert_sim_outcomes failed')

    if upsert_strategy_performance([{
        'strategy': 'momentum_breakout_20',
        'market': 'INDIA',
        'predictions': 1,
        'resolved': 1,
        'wins': 1,
        'losses': 0,
        'ambiguous': 0,
        'win_rate': 1.0,
    }]) != 1:
        return _fail('upsert_strategy_performance failed')

    stats = get_simulation_stats()
    if 'simulation_runs' not in stats:
        return _fail('get_simulation_stats missing keys')

    if not list_runs(limit=1):
        return _fail('list_runs returned empty after insert')

    dashboard = get_simulation_dashboard()
    if not dashboard.get('ok'):
        return _fail('get_simulation_dashboard not ok')

    cleanup = get_connection()
    try:
        cleanup.execute('DELETE FROM historical_simulated_outcomes WHERE ticker = ?', ('__TEST_SIM__',))
        cleanup.execute('DELETE FROM historical_simulated_predictions WHERE ticker = ?', ('__TEST_SIM__',))
        cleanup.execute('DELETE FROM historical_simulation_runs WHERE run_id = ?', (test_run,))
        cleanup.execute(
            "DELETE FROM historical_strategy_performance WHERE strategy = ? AND market = ?",
            ('momentum_breakout_20', 'INDIA'),
        )
        cleanup.commit()
    finally:
        cleanup.close()

    print('HISTORICAL_SIMULATION_VALIDATE_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
