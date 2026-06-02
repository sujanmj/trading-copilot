#!/usr/bin/env python3
"""
Temp-DB tests for historical simulation idempotency.

Usage:
  python scripts/test_historical_simulation_idempotency.py

Prints HISTORICAL_SIMULATION_IDEMPOTENCY_OK on success.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if str(Path.cwd().resolve()) != str(PROJECT_ROOT.resolve()):
    import os

    os.chdir(PROJECT_ROOT)

TEST_TICKER = 'HISTIDEMTEST'


def _fail(msg: str) -> int:
    print(f'HISTORICAL_SIMULATION_IDEMPOTENCY_FAIL: {msg}', file=sys.stderr)
    return 1


def _build_candles(count: int = 80, *, breakout_at: int | None = None) -> list[dict]:
    candles: list[dict] = []
    price = 100.0
    for idx in range(count):
        day = idx + 1
        date = f'2025-01-{day:02d}' if day <= 31 else f'2025-02-{day - 31:02d}'
        high = price + 1.0
        low = price - 1.0
        close = price
        volume = 1000.0
        if breakout_at is not None and idx == breakout_at:
            close = high + 5.0
            high = close + 1.0
            volume = 3000.0
        candles.append({
            'market': 'INDIA',
            'ticker': TEST_TICKER,
            'date': date,
            'source': 'test',
            'open': price,
            'high': high,
            'low': low,
            'close': close,
            'volume': volume,
            'fake_prices': 0,
        })
        price = close
    return candles


def _sim_counts(db_path: Path) -> dict[str, int]:
    import sqlite3

    conn = sqlite3.connect(str(db_path))
    try:
        counts = {}
        for table in (
            'historical_simulation_runs',
            'historical_simulated_predictions',
            'historical_simulated_outcomes',
            'historical_strategy_performance',
        ):
            row = conn.execute(f'SELECT COUNT(*) FROM {table}').fetchone()
            counts[table] = int(row[0]) if row else 0
        row = conn.execute('SELECT COUNT(*) FROM historical_prices').fetchone()
        counts['historical_prices'] = int(row[0]) if row else 0
        return counts
    finally:
        conn.close()


def _run_tests(db_path: Path) -> str | None:
    from backend.analytics.historical_prediction_simulator import run_historical_simulation
    from backend.storage.historical_market_store import (
        delete_simulation_by_params_hash,
        find_run_by_params_hash,
        get_duplicate_params_groups,
        init_db,
        upsert_prices,
    )

    if not init_db():
        return 'init_db failed'

    candles = _build_candles(80, breakout_at=70)
    upsert_prices(candles)
    prices_before = _sim_counts(db_path)['historical_prices']

    from_date = candles[65]['date']
    to_date = candles[-1]['date']
    sim_kwargs = dict(
        market='INDIA',
        from_date=from_date,
        to_date=to_date,
        strategies=['momentum_breakout_20'],
        limit_tickers=1,
        max_signals=5,
    )

    counts_before = _sim_counts(db_path)
    dry_summary = run_historical_simulation(**sim_kwargs, dry_run=True, write=False)
    counts_after_dry = _sim_counts(db_path)
    for table in (
        'historical_simulation_runs',
        'historical_simulated_predictions',
        'historical_simulated_outcomes',
        'historical_strategy_performance',
    ):
        if counts_after_dry[table] != counts_before[table]:
            return f'dry-run changed {table}: {counts_before[table]} -> {counts_after_dry[table]}'
    if dry_summary.get('written', 0) != 0:
        return 'dry-run written should be 0'

    first = run_historical_simulation(**sim_kwargs, dry_run=False, write=True)
    if first.get('written', 0) <= 0:
        return 'first write should write rows'
    counts_after_first = _sim_counts(db_path)
    if counts_after_first['historical_simulation_runs'] != 1:
        return f'expected 1 run after first write, got {counts_after_first["historical_simulation_runs"]}'

    second = run_historical_simulation(**sim_kwargs, dry_run=False, write=True)
    if second.get('written', 0) != 0:
        return f'second write should be 0, got {second.get("written")}'
    if not second.get('duplicate_existing_run'):
        return 'second write should report duplicate_existing_run'
    counts_after_second = _sim_counts(db_path)
    if counts_after_second != counts_after_first:
        return 'second write changed simulation table counts'

    replace = run_historical_simulation(
        **sim_kwargs,
        dry_run=False,
        write=True,
        replace_existing=True,
    )
    if replace.get('written', 0) <= 0:
        return 'replace-existing should write rows'
    counts_after_replace = _sim_counts(db_path)
    if counts_after_replace['historical_simulation_runs'] != 1:
        return 'replace-existing should keep exactly one run'

    params_hash = first.get('params_hash')
    if not params_hash:
        return 'missing params_hash'

    dup = run_historical_simulation(**sim_kwargs, dry_run=False, write=True, allow_duplicate=True)
    if dup.get('written', 0) <= 0:
        return 'allow-duplicate should write rows'
    if _sim_counts(db_path)['historical_simulation_runs'] < 2:
        return 'allow-duplicate should add a second run'

    existing = find_run_by_params_hash(params_hash)
    if not existing:
        return 'find_run_by_params_hash failed'
    delete_simulation_by_params_hash(params_hash, keep_run_id=existing['run_id'])
    if get_duplicate_params_groups():
        return 'cleanup should remove duplicate params_hash groups'

    counts_final = _sim_counts(db_path)
    if counts_final['historical_simulation_runs'] != 1:
        return f'expected 1 run after cleanup, got {counts_final["historical_simulation_runs"]}'
    if counts_final['historical_prices'] != prices_before:
        return 'historical_prices changed during simulation tests'

    return None


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / 'historical_market_memory.db'
        with patch('backend.storage.historical_market_store.get_historical_db_path', return_value=db_path):
            with patch('backend.storage.historical_market_store.DATA_DIR', Path(tmp)):
                with patch(
                    'backend.analytics.historical_prediction_simulator._load_tickers',
                    return_value=[TEST_TICKER],
                ):
                    err = _run_tests(db_path)
                    if err:
                        return _fail(err)

    print('HISTORICAL_SIMULATION_IDEMPOTENCY_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
