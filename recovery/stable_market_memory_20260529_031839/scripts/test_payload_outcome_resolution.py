#!/usr/bin/env python3
"""
Synthetic tests for payload-based market memory outcome resolution.

Usage:
  python scripts/test_payload_outcome_resolution.py

Prints exactly PAYLOAD_OUTCOME_RESOLUTION_OK on success; exits 1 on failure.
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

TEST_TICKER = '__TEST_PAYLOAD_OUTCOME__'
TEST_TS = '2026-01-02T00:00:00+00:00'
TEST_HOLDING = 'test_payload'


def _fail(msg: str) -> int:
    print(f'PAYLOAD_OUTCOME_RESOLUTION_FAIL: {msg}', file=sys.stderr)
    return 1


def _cleanup(conn, prediction_ids: list[str]) -> None:
    for prediction_id in prediction_ids:
        conn.execute(
            'DELETE FROM outcomes WHERE prediction_id = ? AND holding_period = ?',
            (prediction_id, TEST_HOLDING),
        )
        conn.execute('DELETE FROM predictions WHERE prediction_id = ?', (prediction_id,))
    conn.commit()


def main() -> int:
    from backend.storage.market_memory_db import get_connection, init_market_memory_db, upsert_prediction
    from backend.storage.market_memory_outcomes import (
        resolve_outcome_from_payload,
        resolve_prediction_outcome,
    )

    if not init_market_memory_db():
        return _fail('init_market_memory_db returned False')

    cases = [
        {
            'name': 'bullish_target_hit',
            'direction': 'BULLISH',
            'raw_payload': {
                'target_hit': True,
                'stop_loss_hit': False,
                'change_1d_pct': 2.5,
                'max_gain_pct': 3.0,
                'max_loss_pct': -0.5,
                'state': 'CLOSED',
            },
            'expect': ('WIN', 'TARGET_HIT'),
        },
        {
            'name': 'bullish_stop_loss_hit',
            'direction': 'BULLISH',
            'raw_payload': {
                'target_hit': False,
                'stop_loss_hit': 'true',
                'change_1d_pct': -1.2,
                'max_gain_pct': 0.4,
                'max_loss_pct': -2.0,
                'state': 'CLOSED',
            },
            'expect': ('LOSS', 'STOP_LOSS_HIT'),
        },
        {
            'name': 'bullish_closed_positive',
            'direction': 'BULLISH',
            'raw_payload': {
                'target_hit': False,
                'stop_loss_hit': False,
                'change_1d_pct': 1.8,
                'max_gain_pct': 2.1,
                'max_loss_pct': -0.3,
                'state': 'EXPIRED',
            },
            'expect': ('WIN', 'EXPIRED'),
        },
        {
            'name': 'bullish_closed_negative',
            'direction': 'BULLISH',
            'raw_payload': {
                'target_hit': False,
                'stop_loss_hit': False,
                'change_1d_pct': -0.9,
                'max_gain_pct': 0.2,
                'max_loss_pct': -1.5,
                'state': 'CLOSED',
            },
            'expect': ('LOSS', 'CLOSED'),
        },
        {
            'name': 'no_evidence',
            'direction': 'BULLISH',
            'raw_payload': {
                'target_hit': False,
                'stop_loss_hit': False,
                'change_1d_pct': None,
                'state': 'ACTIVE',
            },
            'expect': None,
        },
    ]

    prediction_ids: list[str] = []
    conn = get_connection()
    try:
        for index, case in enumerate(cases):
            prediction_id = upsert_prediction({
                'ticker': TEST_TICKER,
                'timestamp': f'2026-01-0{index + 3}T00:00:00+00:00',
                'source': 'payload_outcome_test',
                'direction': case['direction'],
                'confidence': 0.7,
                'reasoning': f'payload outcome test: {case["name"]}',
                'raw_payload': case['raw_payload'],
            })
            if not prediction_id:
                return _fail(f'upsert_prediction failed for {case["name"]}')
            prediction_ids.append(prediction_id)

            prediction = {
                'prediction_id': prediction_id,
                'direction': case['direction'],
                'raw_payload': case['raw_payload'],
            }
            outcome_payload = resolve_outcome_from_payload(
                prediction,
                holding_period=TEST_HOLDING,
            )

            if case['expect'] is None:
                if outcome_payload is not None:
                    return _fail(f'{case["name"]}: expected skip, got payload')
                continue

            if outcome_payload is None:
                return _fail(f'{case["name"]}: expected outcome, got None')

            expected_resolved, expected_expiry = case['expect']
            if outcome_payload.get('resolved_as') != expected_resolved:
                return _fail(
                    f'{case["name"]}: resolved_as={outcome_payload.get("resolved_as")} '
                    f'expected {expected_resolved}',
                )
            if outcome_payload.get('expiry_result') != expected_expiry:
                return _fail(
                    f'{case["name"]}: expiry_result={outcome_payload.get("expiry_result")} '
                    f'expected {expected_expiry}',
                )

            if not resolve_prediction_outcome(prediction_id, outcome_payload):
                return _fail(f'resolve_prediction_outcome failed for {case["name"]}')

            row = conn.execute(
                """
                SELECT resolved_as, expiry_result, actual_move, high, low
                FROM outcomes
                WHERE prediction_id = ? AND holding_period = ?
                """,
                (prediction_id, TEST_HOLDING),
            ).fetchone()
            if row is None:
                return _fail(f'outcome row missing for {case["name"]}')
            if row['resolved_as'] != expected_resolved:
                return _fail(f'db resolved_as mismatch for {case["name"]}')
            if row['expiry_result'] != expected_expiry:
                return _fail(f'db expiry_result mismatch for {case["name"]}')

        _cleanup(conn, prediction_ids)
    finally:
        conn.close()

    print('PAYLOAD_OUTCOME_RESOLUTION_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
