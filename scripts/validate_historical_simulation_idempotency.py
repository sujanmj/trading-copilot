#!/usr/bin/env python3
"""
Validate historical simulation idempotency on the live historical DB.

Usage:
  python scripts/validate_historical_simulation_idempotency.py

Prints HISTORICAL_SIMULATION_IDEMPOTENCY_VALIDATE_OK on success.
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
    print(f'HISTORICAL_SIMULATION_IDEMPOTENCY_VALIDATE_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.analytics.historical_prediction_simulator import run_historical_simulation
    from backend.storage.historical_market_store import (
        get_connection,
        get_duplicate_params_groups,
        get_stats,
        init_db,
        rebuild_strategy_performance,
    )
    from backend.storage.market_memory_db import get_market_memory_stats

    if not init_db():
        return _fail('init_db returned False')

    duplicate_groups = get_duplicate_params_groups()
    print(f'[HIST_SIM_VALIDATE] duplicate_params_groups={len(duplicate_groups)}')
    if duplicate_groups:
        return _fail(
            f'duplicate params_hash groups remain: {len(duplicate_groups)}',
        )

    conn = get_connection()
    try:
        missing_hash = conn.execute(
            """
            SELECT COUNT(*) AS cnt
            FROM historical_simulation_runs
            WHERE params_hash IS NULL OR params_hash = ''
            """
        ).fetchone()
        if missing_hash and int(missing_hash['cnt']) > 0:
            print(
                f'[HIST_SIM_VALIDATE] runs_missing_params_hash={missing_hash["cnt"]}',
            )

        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_hsr_params_hash'"
        ).fetchone()
        if not row:
            return _fail('missing index idx_hsr_params_hash')
    finally:
        conn.close()

    canonical_before = get_market_memory_stats()
    hist_before = get_stats()
    sim_counts_before = {
        key: int(hist_before.get(key) or 0)
        for key in (
            'historical_simulation_runs',
            'historical_simulated_predictions',
            'historical_simulated_outcomes',
            'historical_strategy_performance',
            'historical_prices',
        )
    }

    dry_summary = run_historical_simulation(
        market='INDIA',
        limit_tickers=1,
        max_signals=1,
        dry_run=True,
        write=False,
    )
    if dry_summary.get('written', 0) != 0:
        return _fail('dry-run reported non-zero written')

    hist_after_dry = get_stats()
    for key, before in sim_counts_before.items():
        after = int(hist_after_dry.get(key) or 0)
        if after != before:
            return _fail(f'dry-run changed {key}: {before} -> {after}')

    rows_written = rebuild_strategy_performance()
    print(f'[HIST_SIM_VALIDATE] strategy_performance_rows={rows_written}')

    canonical_after = get_market_memory_stats()
    if canonical_before.get('predictions') != canonical_after.get('predictions'):
        return _fail('canonical predictions changed during validation')
    if canonical_before.get('outcomes') != canonical_after.get('outcomes'):
        return _fail('canonical outcomes changed during validation')

    print('HISTORICAL_SIMULATION_IDEMPOTENCY_VALIDATE_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
