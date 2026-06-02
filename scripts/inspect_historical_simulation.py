#!/usr/bin/env python3
"""
Inspect historical simulation runs and strategy performance.

Usage:
  python scripts/inspect_historical_simulation.py

Prints summary tables; exits 0 when DB is readable.
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


def main() -> int:
    from backend.storage.historical_market_store import (
        count_unique_params_hashes,
        get_duplicate_params_groups,
        get_simulation_stats,
        get_strategy_performance,
        init_db,
        list_runs,
    )

    init_db()
    stats = get_simulation_stats()
    runs = list_runs(limit=20)
    strategies = get_strategy_performance()
    duplicate_groups = get_duplicate_params_groups()
    unique_params_hashes = count_unique_params_hashes()
    latest_run = runs[0] if runs else None

    print('[HIST_SIM_INSPECT] stats=' + json.dumps(stats, default=str))
    print(f'[HIST_SIM_INSPECT] runs={len(runs)}')
    print(f'[HIST_SIM_INSPECT] duplicate_params_groups={len(duplicate_groups)}')
    print(f'[HIST_SIM_INSPECT] unique_params_hash_count={unique_params_hashes}')
    if latest_run:
        print(
            f'[HIST_SIM_INSPECT] latest_run_id={latest_run.get("run_id")} '
            f'market={latest_run.get("market")} '
            f'params_hash={latest_run.get("params_hash")} '
            f'signals={latest_run.get("generated_predictions")} '
            f'created_at={latest_run.get("created_at")}',
        )
    else:
        print('[HIST_SIM_INSPECT] latest_run_id=None')

    for run in runs[:10]:
        print(
            f"  run_id={run.get('run_id')} market={run.get('market')} "
            f"params_hash={run.get('params_hash')} "
            f"signals={run.get('generated_predictions')} wins={run.get('wins')} "
            f"losses={run.get('losses')} ambiguous={run.get('ambiguous')}",
        )

    print(f'[HIST_SIM_INSPECT] strategy_performance={len(strategies)}')
    for row in strategies[:20]:
        print(
            f"  strategy={row.get('strategy')} market={row.get('market')} "
            f"predictions={row.get('predictions')} win_rate={row.get('win_rate')} "
            f"expectancy={row.get('expectancy_pct')}",
        )
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
