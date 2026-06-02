#!/usr/bin/env python3
"""
Smoke test for broker prediction intelligence (Stage 23).

Usage:
  python scripts/test_broker_prediction_intelligence.py

Prints exactly BROKER_PREDICTION_INTELLIGENCE_OK on success.
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

TEST_TICKER = '__TEST_BROKER_INTEL__'


def _fail(msg: str) -> int:
    print(f'BROKER_PREDICTION_INTELLIGENCE_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.analytics.broker_consensus_score import score_broker_evidence
    from backend.analytics.broker_prediction_intelligence import (
        compare_our_predictions_vs_brokers,
        is_outcome_evidence,
        make_broker_prediction_id,
        normalize_broker_pick_stance,
        prepare_broker_pick_for_import,
    )
    from backend.storage.market_memory_db import get_connection, init_market_memory_db, upsert_broker_prediction

    stance, conf, notes = normalize_broker_pick_stance('WATCHLIST')
    if stance != 'WATCH':
        return _fail(f'WATCHLIST should normalize to WATCH, got {stance}')
    if 'watchlist_not_bullish' not in notes:
        return _fail('expected watchlist_not_bullish note')

    if not is_outcome_evidence({'target_type': 'eod_gainer', 'ticker': 'X'}):
        return _fail('eod_gainer should be outcome evidence')
    if is_outcome_evidence({'stance': 'BUY', 'ticker': 'X', 'broker_source': 'Test'}):
        return _fail('BUY pick should not be outcome evidence')

    pick = prepare_broker_pick_for_import({
        'broker_source': 'TestBroker',
        'ticker': TEST_TICKER,
        'stance': 'BUY',
        'prediction_date': '2026-05-30',
        'confidence': 0.7,
    })
    if pick is None:
        return _fail('prepare_broker_pick_for_import returned None')

    pred_id = pick.get('prediction_id') or ''
    if not pred_id.startswith('broker:'):
        return _fail(f'prediction_id must start with broker:, got {pred_id}')
    if pick.get('dedupe_key') != pred_id:
        return _fail('dedupe_key must match prediction_id')

    stable_id = make_broker_prediction_id(pick)
    if stable_id != pred_id:
        return _fail('make_broker_prediction_id not stable')

    rejected = prepare_broker_pick_for_import({
        'broker_source': 'TestBroker',
        'ticker': TEST_TICKER,
        'stance': 'TOP_GAINER',
        'target_type': 'eod_gainer',
    })
    if rejected is not None:
        return _fail('outcome row should be rejected at prepare time')

    if not init_market_memory_db():
        return _fail('init_market_memory_db returned False')

    row_id = upsert_broker_prediction(pick, update_existing=True)
    if row_id is None:
        return _fail('upsert_broker_prediction failed')

    score = score_broker_evidence({'ticker': TEST_TICKER, 'direction': 'BUY'})
    adj = score.get('confidence_adjustment')
    if adj is None or not -20 <= int(adj) <= 20:
        return _fail(f'confidence_adjustment out of range: {adj}')

    comparison = compare_our_predictions_vs_brokers(ticker=TEST_TICKER)
    if not comparison.get('ok'):
        return _fail('compare_our_predictions_vs_brokers failed')

    conn = get_connection()
    try:
        conn.execute(
            'DELETE FROM broker_predictions WHERE ticker = ?',
            (TEST_TICKER,),
        )
        conn.commit()
    finally:
        conn.close()

    print('BROKER_PREDICTION_INTELLIGENCE_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
