#!/usr/bin/env python3
"""
Validate simulation adapter exposes full strategy coverage.

Prints exactly SIMULATION_STRATEGY_COVERAGE_OK on success.
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


def _fail(msg: str) -> int:
    print(f'SIMULATION_STRATEGY_COVERAGE_FAIL: {msg}', file=sys.stderr)
    return 1


def _distinct_performance_strategies() -> set[str]:
    from backend.storage.historical_market_store import get_connection, init_db

    init_db()
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT DISTINCT strategy
            FROM historical_strategy_performance
            WHERE strategy IS NOT NULL AND TRIM(strategy) != ''
            """
        ).fetchall()
    finally:
        conn.close()
    return {str(row['strategy']) for row in rows if row['strategy']}


def _distinct_outcome_strategies() -> set[str]:
    from backend.storage.historical_market_store import get_connection, init_db

    init_db()
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT DISTINCT strategy
            FROM historical_simulated_outcomes
            WHERE strategy IS NOT NULL AND TRIM(strategy) != ''
            """
        ).fetchall()
    finally:
        conn.close()
    return {str(row['strategy']) for row in rows if row['strategy']}


def main() -> int:
    from backend.analytics.simulation_performance_adapter import (
        KNOWN_STRATEGIES,
        get_simulation_summary,
        get_strategy_performance,
    )
    from backend.storage.historical_market_store import get_simulation_stats, init_db

    if not init_db():
        return _fail('init_db failed')

    stats = get_simulation_stats()
    fake_predictions = int(stats.get('simulated_predictions') or 0)
    if stats.get('simulation_runs', 0) > 0 and fake_predictions <= 0:
        pass  # ok — no fake_predictions column; simulated data is real OHLCV derived

    db_strategies = _distinct_performance_strategies()
    outcome_strategies = _distinct_outcome_strategies()
    db_count = len(db_strategies)

    summary = get_simulation_summary()
    payload = get_strategy_performance()
    adapter_rows = payload.get('rows') or []
    adapter_names = {str(row.get('strategy') or '') for row in adapter_rows if row.get('strategy')}

    if len(adapter_names) < db_count:
        return _fail(
            f'adapter strategies={len(adapter_names)} fewer than DB performance={db_count}',
        )

    missing_from_db = db_strategies - adapter_names
    if missing_from_db:
        return _fail(f'adapter missing DB strategies: {sorted(missing_from_db)}')

    if 'momentum_breakout_20' in outcome_strategies and 'momentum_breakout_20' not in adapter_names:
        return _fail('momentum_breakout_20 present in outcomes but missing from adapter')

    for name in KNOWN_STRATEGIES:
        if name in outcome_strategies and name not in adapter_names:
            return _fail(f'known strategy {name} has outcomes but missing from adapter')

    if int(summary.get('strategy_count') or 0) != len(adapter_rows):
        return _fail('summary strategy_count does not match adapter rows')

    print(f'[SIM_COVERAGE] db_strategies={db_count}')
    print(f'[SIM_COVERAGE] outcome_strategies={len(outcome_strategies)}')
    print(f'[SIM_COVERAGE] adapter_strategies={len(adapter_names)}')
    print('SIMULATION_STRATEGY_COVERAGE_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
