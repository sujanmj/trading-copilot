#!/usr/bin/env python3
"""
Smoke test for scripts/delete_anomalous_price_outcomes.py.

Usage:
  python scripts/test_delete_anomalous_price_outcomes.py

Prints exactly DELETE_ANOMALOUS_PRICE_OUTCOMES_OK on success; exits 1 on failure.
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

TEST_TICKER = '__TEST_ANOMALOUS_PRICE_OUTCOME__'
TEST_HOLDING = 'test_anomalous_price'
TEST_PREDICTION_ID = 'test:anomalous_price_outcome'


def _fail(msg: str) -> int:
    print(f'DELETE_ANOMALOUS_PRICE_OUTCOMES_FAIL: {msg}', file=sys.stderr)
    return 1


def _cleanup(conn) -> None:
    conn.execute(
        'DELETE FROM outcomes WHERE prediction_id = ? AND holding_period = ?',
        (TEST_PREDICTION_ID, TEST_HOLDING),
    )
    conn.execute('DELETE FROM predictions WHERE prediction_id = ?', (TEST_PREDICTION_ID,))
    conn.commit()


def main() -> int:
    from backend.storage.market_memory_db import get_connection, init_market_memory_db, upsert_prediction
    from backend.storage.market_memory_outcomes import resolve_prediction_outcome
    from scripts.delete_anomalous_price_outcomes import delete_anomalous_price_outcomes

    if not init_market_memory_db():
        return _fail('init_market_memory_db returned False')

    conn = get_connection()
    try:
        _cleanup(conn)

        upsert_prediction({
            'prediction_id': TEST_PREDICTION_ID,
            'ticker': TEST_TICKER,
            'timestamp': '2026-01-01T00:00:00+00:00',
            'source': 'delete_anomalous_test',
            'direction': 'BULLISH',
            'confidence': 0.5,
            'reasoning': 'synthetic anomalous price outcome test',
            'raw_payload': {
                'entry_price': 310.0,
                'target_price': 320.0,
                'stop_loss': 300.0,
            },
        })

        if not resolve_prediction_outcome(TEST_PREDICTION_ID, {
            'prediction_id': TEST_PREDICTION_ID,
            'actual_move': 628.68,
            'high': 2258.90,
            'low': None,
            'expiry_result': 'TARGET_HIT_BY_PRICE',
            'resolved_as': 'WIN',
            'holding_period': TEST_HOLDING,
            'raw_payload': {
                'source': 'latest_market_data_price_resolution',
                'entry_price': 310.0,
                'target_price': 320.0,
                'stop_loss': 300.0,
                'latest_price': 2258.90,
            },
        }):
            return _fail('resolve_prediction_outcome failed for synthetic row')

        row = conn.execute(
            """
            SELECT prediction_id
            FROM outcomes
            WHERE prediction_id = ? AND holding_period = ?
            """,
            (TEST_PREDICTION_ID, TEST_HOLDING),
        ).fetchone()
        if row is None:
            return _fail('synthetic outcome row not found before dry-run')

        dry_summary = delete_anomalous_price_outcomes(confirm=False)
        if dry_summary.get('deleted', 0) != 0:
            return _fail(f'dry-run deleted rows: {dry_summary.get("deleted")}')
        if not dry_summary.get('dry_run'):
            return _fail('dry-run summary dry_run flag is False')

        row = conn.execute(
            """
            SELECT prediction_id
            FROM outcomes
            WHERE prediction_id = ? AND holding_period = ?
            """,
            (TEST_PREDICTION_ID, TEST_HOLDING),
        ).fetchone()
        if row is None:
            return _fail('synthetic outcome row missing after dry-run')

        confirm_summary = delete_anomalous_price_outcomes(
            confirm=True,
            only_prediction_ids={TEST_PREDICTION_ID},
        )
        if confirm_summary.get('deleted', 0) != 1:
            return _fail(
                f'--confirm deleted {confirm_summary.get("deleted")} rows, expected 1',
            )

        row = conn.execute(
            """
            SELECT prediction_id
            FROM outcomes
            WHERE prediction_id = ? AND holding_period = ?
            """,
            (TEST_PREDICTION_ID, TEST_HOLDING),
        ).fetchone()
        if row is not None:
            return _fail('synthetic outcome row still present after --confirm')

        _cleanup(conn)
    finally:
        conn.close()

    print('DELETE_ANOMALOUS_PRICE_OUTCOMES_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
