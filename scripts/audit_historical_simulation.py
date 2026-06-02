#!/usr/bin/env python3
"""
Audit historical simulation integrity and safety constraints.

Usage:
  python scripts/audit_historical_simulation.py

Prints exactly HISTORICAL_SIMULATION_AUDIT_OK on success.
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


def _fail(msg: str) -> int:
    print(f'HISTORICAL_SIMULATION_AUDIT_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.storage.historical_market_store import (
        get_connection,
        get_excluded_simulation_dates,
        get_sim_outcomes,
        get_sim_predictions,
        init_db,
    )
    from backend.storage.market_memory_db import get_market_memory_stats

    init_db()
    canonical_before = get_market_memory_stats()

    predictions = get_sim_predictions()
    outcomes = get_sim_outcomes()

    if not predictions and not outcomes:
        print('[HIST_SIM_AUDIT] no simulation rows yet — schema checks only')

    seen_pred_ids: set[str] = set()
    for pred in predictions:
        sim_id = pred.get('sim_prediction_id')
        if not sim_id or sim_id == '0':
            return _fail(f'invalid sim_prediction_id: {sim_id!r}')
        if sim_id in seen_pred_ids:
            return _fail(f'duplicate sim_prediction_id: {sim_id}')
        seen_pred_ids.add(sim_id)

        features_raw = pred.get('features_json')
        features = features_raw
        if isinstance(features_raw, str):
            try:
                features = json.loads(features_raw)
            except json.JSONDecodeError:
                features = {}
        if isinstance(features, dict) and features.get('fake_prediction') is True:
            return _fail(f'fake_prediction flag on {sim_id}')

        market = str(pred.get('market') or 'INDIA').strip().upper()
        ticker = str(pred.get('ticker') or '').strip().upper()
        signal_date = pred.get('signal_date')
        if signal_date and ticker:
            excluded = get_excluded_simulation_dates(market, ticker)
            if signal_date in excluded:
                return _fail(f'excluded anomaly date used as signal: {ticker} {signal_date}')

    pred_by_id = {row['sim_prediction_id']: row for row in predictions}
    for outcome in outcomes:
        sim_id = outcome.get('sim_prediction_id')
        pred = pred_by_id.get(sim_id)
        if not pred:
            continue
        signal_date = pred.get('signal_date')
        evidence_raw = outcome.get('evidence_json')
        evidence = evidence_raw
        if isinstance(evidence_raw, str):
            try:
                evidence = json.loads(evidence_raw)
            except json.JSONDecodeError:
                evidence = {}
        if isinstance(evidence, dict):
            if evidence.get('uses_future_data') is True:
                return _fail(f'lookahead flagged on outcome {sim_id}')
            resolved_on = evidence.get('resolved_on')
            if resolved_on and signal_date and resolved_on <= signal_date:
                if outcome.get('result') not in ('UNRESOLVED',):
                    return _fail(
                        f'signal candle in outcome path: {sim_id} '
                        f'signal={signal_date} resolved_on={resolved_on}',
                    )

    conn = get_connection()
    try:
        dup = conn.execute(
            """
            SELECT sim_prediction_id, COUNT(*) AS cnt
            FROM historical_simulated_predictions
            GROUP BY sim_prediction_id
            HAVING cnt > 1
            """
        ).fetchall()
        if dup:
            return _fail(f'duplicate sim_prediction_id rows: {len(dup)}')

        zero_ids = conn.execute(
            """
            SELECT COUNT(*) AS cnt
            FROM historical_simulated_predictions
            WHERE sim_prediction_id IS NULL OR sim_prediction_id = '0'
            """
        ).fetchone()
        if zero_ids and int(zero_ids['cnt']) > 0:
            return _fail(f'sim_prediction_id=0 count={zero_ids["cnt"]}')
    finally:
        conn.close()

    canonical_after = get_market_memory_stats()
    if canonical_before.get('predictions') != canonical_after.get('predictions'):
        return _fail('canonical predictions count changed during audit read')
    if canonical_before.get('outcomes') != canonical_after.get('outcomes'):
        return _fail('canonical outcomes count changed during audit read')

    print('HISTORICAL_SIMULATION_AUDIT_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
