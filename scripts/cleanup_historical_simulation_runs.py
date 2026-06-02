#!/usr/bin/env python3
"""
Clean up duplicate or test historical simulation runs.

Never touches historical_prices or canonical market memory.

Usage:
  python scripts/cleanup_historical_simulation_runs.py --dry-run --duplicates-only --keep-latest
  python scripts/cleanup_historical_simulation_runs.py --duplicates-only --keep-latest
  python scripts/cleanup_historical_simulation_runs.py --run-id hsr:abc123
  python scripts/cleanup_historical_simulation_runs.py --test-runs-only

Prints HISTORICAL_SIMULATION_CLEANUP_OK on success.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if str(Path.cwd().resolve()) != str(PROJECT_ROOT.resolve()):
    import os

    os.chdir(PROJECT_ROOT)


def _fail(msg: str) -> int:
    print(f'HISTORICAL_SIMULATION_CLEANUP_FAIL: {msg}', file=sys.stderr)
    return 1


def _is_test_run(run: dict) -> bool:
    run_id = str(run.get('run_id') or '')
    if run_id.startswith('__TEST') or '__TEST' in run_id:
        return True
    params_raw = run.get('params_json')
    params = params_raw
    if isinstance(params_raw, str):
        try:
            params = json.loads(params_raw)
        except json.JSONDecodeError:
            params = {}
    if isinstance(params, dict) and params.get('test') is True:
        return True
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description='Clean up historical simulation runs.')
    parser.add_argument('--dry-run', action='store_true', default=False)
    parser.add_argument('--duplicates-only', action='store_true', default=False)
    parser.add_argument('--keep-latest', action='store_true', default=False)
    parser.add_argument('--run-id', default=None, help='Delete a specific simulation run')
    parser.add_argument('--test-runs-only', action='store_true', default=False)
    args = parser.parse_args()

    from backend.storage.historical_market_store import (
        delete_simulation_by_params_hash,
        delete_simulation_run_cascade,
        get_connection,
        get_duplicate_params_groups,
        init_db,
        list_runs,
        rebuild_strategy_performance,
    )

    if not init_db():
        return _fail('init_db returned False')

    totals = {
        'duplicate_groups': 0,
        'runs_deleted': 0,
        'predictions_deleted': 0,
        'outcomes_deleted': 0,
    }

    if args.run_id:
        if args.dry_run:
            conn = get_connection()
            try:
                pred_count = conn.execute(
                    'SELECT COUNT(*) AS cnt FROM historical_simulated_predictions WHERE run_id = ?',
                    (args.run_id,),
                ).fetchone()
                outcome_count = conn.execute(
                    """
                    SELECT COUNT(*) AS cnt
                    FROM historical_simulated_outcomes o
                    JOIN historical_simulated_predictions p
                      ON p.sim_prediction_id = o.sim_prediction_id
                    WHERE p.run_id = ?
                    """,
                    (args.run_id,),
                ).fetchone()
                run_count = conn.execute(
                    'SELECT COUNT(*) AS cnt FROM historical_simulation_runs WHERE run_id = ?',
                    (args.run_id,),
                ).fetchone()
                totals['runs_deleted'] = int(run_count['cnt']) if run_count else 0
                totals['predictions_deleted'] = int(pred_count['cnt']) if pred_count else 0
                totals['outcomes_deleted'] = int(outcome_count['cnt']) if outcome_count else 0
            finally:
                conn.close()
        else:
            result = delete_simulation_run_cascade(args.run_id)
            for key in ('runs_deleted', 'predictions_deleted', 'outcomes_deleted'):
                totals[key] += int(result.get(key) or 0)
            rebuild_strategy_performance()
    elif args.test_runs_only:
        runs = list_runs(limit=None)
        test_runs = [run for run in runs if _is_test_run(run)]
        for run in test_runs:
            if args.dry_run:
                conn = get_connection()
                try:
                    run_id = run['run_id']
                    pred_count = conn.execute(
                        'SELECT COUNT(*) AS cnt FROM historical_simulated_predictions WHERE run_id = ?',
                        (run_id,),
                    ).fetchone()
                    outcome_count = conn.execute(
                        """
                        SELECT COUNT(*) AS cnt
                        FROM historical_simulated_outcomes o
                        JOIN historical_simulated_predictions p
                          ON p.sim_prediction_id = o.sim_prediction_id
                        WHERE p.run_id = ?
                        """,
                        (run_id,),
                    ).fetchone()
                    totals['runs_deleted'] += 1
                    totals['predictions_deleted'] += int(pred_count['cnt']) if pred_count else 0
                    totals['outcomes_deleted'] += int(outcome_count['cnt']) if outcome_count else 0
                finally:
                    conn.close()
            else:
                result = delete_simulation_run_cascade(run['run_id'])
                for key in ('runs_deleted', 'predictions_deleted', 'outcomes_deleted'):
                    totals[key] += int(result.get(key) or 0)
        if not args.dry_run and test_runs:
            rebuild_strategy_performance()
    elif args.duplicates_only:
        duplicate_groups = get_duplicate_params_groups()
        totals['duplicate_groups'] = len(duplicate_groups)

        conn = get_connection()
        try:
            for group in duplicate_groups:
                params_hash = group['params_hash']
                rows = conn.execute(
                    """
                    SELECT run_id, created_at
                    FROM historical_simulation_runs
                    WHERE params_hash = ?
                    ORDER BY created_at DESC
                    """,
                    (params_hash,),
                ).fetchall()
                if len(rows) <= 1:
                    continue

                keep_run_id = rows[0]['run_id'] if args.keep_latest else None
                delete_ids = [
                    row['run_id']
                    for row in (rows[1:] if args.keep_latest else rows)
                ]

                if args.dry_run:
                    for run_id in delete_ids:
                        pred_count = conn.execute(
                            'SELECT COUNT(*) AS cnt FROM historical_simulated_predictions WHERE run_id = ?',
                            (run_id,),
                        ).fetchone()
                        outcome_count = conn.execute(
                            """
                            SELECT COUNT(*) AS cnt
                            FROM historical_simulated_outcomes o
                            JOIN historical_simulated_predictions p
                              ON p.sim_prediction_id = o.sim_prediction_id
                            WHERE p.run_id = ?
                            """,
                            (run_id,),
                        ).fetchone()
                        totals['runs_deleted'] += 1
                        totals['predictions_deleted'] += int(pred_count['cnt']) if pred_count else 0
                        totals['outcomes_deleted'] += int(outcome_count['cnt']) if outcome_count else 0
                elif args.keep_latest:
                    result = delete_simulation_by_params_hash(
                        params_hash,
                        keep_run_id=keep_run_id,
                    )
                    for key in ('runs_deleted', 'predictions_deleted', 'outcomes_deleted'):
                        totals[key] += int(result.get(key) or 0)
                else:
                    for run_id in delete_ids:
                        result = delete_simulation_run_cascade(run_id)
                        for key in ('runs_deleted', 'predictions_deleted', 'outcomes_deleted'):
                            totals[key] += int(result.get(key) or 0)
        finally:
            conn.close()

        if not args.dry_run and duplicate_groups:
            rebuild_strategy_performance()
    else:
        return _fail('specify --run-id, --test-runs-only, or --duplicates-only')

    print(f'[HIST_SIM_CLEANUP] duplicate_groups={totals["duplicate_groups"]}')
    print(f'[HIST_SIM_CLEANUP] runs_deleted={totals["runs_deleted"]}')
    print(f'[HIST_SIM_CLEANUP] predictions_deleted={totals["predictions_deleted"]}')
    print(f'[HIST_SIM_CLEANUP] outcomes_deleted={totals["outcomes_deleted"]}')
    print('HISTORICAL_SIMULATION_CLEANUP_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
