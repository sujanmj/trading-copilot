#!/usr/bin/env python3
"""
Smoke test for market memory learning engine.

Usage:
  python scripts/test_market_memory_learning.py

Prints exactly MARKET_MEMORY_LEARNING_OK on success; exits 1 on failure.
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

TEST_TICKER = '__TEST_LEARNING__'
TEST_HOLDING = 'test_learning'


def _fail(msg: str) -> int:
    print(f'MARKET_MEMORY_LEARNING_FAIL: {msg}', file=sys.stderr)
    return 1


def _cleanup(conn, prediction_ids: list[str]) -> None:
    for prediction_id in prediction_ids:
        conn.execute('DELETE FROM outcomes WHERE prediction_id = ?', (prediction_id,))
        conn.execute('DELETE FROM predictions WHERE prediction_id = ?', (prediction_id,))
    conn.execute('DELETE FROM outcomes WHERE prediction_id IN (SELECT prediction_id FROM predictions WHERE ticker = ?)', (TEST_TICKER,))
    conn.execute('DELETE FROM predictions WHERE ticker = ?', (TEST_TICKER,))
    conn.commit()


def main() -> int:
    from backend.analytics.market_memory_learning import get_grouped_performance, get_learning_summary
    from backend.storage.market_memory_db import get_connection, init_market_memory_db, upsert_outcome, upsert_prediction

    if not init_market_memory_db():
        return _fail('init_market_memory_db returned False')

    conn = get_connection()
    try:
        _cleanup(conn, [])
    finally:
        conn.close()

    prediction_ids: list[str] = []
    try:
        cases = [
            {
                'confidence_label': 'HIGH',
                'resolved_as': 'WIN',
                'actual_move': 2.5,
                'signal_stack': {
                    'signal_type': 'test_signal',
                    'prediction_horizon': 'intraday',
                    'broker_consensus': {'agreement_direction': 'BULLISH'},
                },
            },
            {
                'confidence_label': 'HIGH',
                'resolved_as': 'WIN',
                'actual_move': 1.0,
                'signal_stack': {
                    'signal_type': 'test_signal',
                    'prediction_horizon': 'intraday',
                    'broker_consensus': {'agreement_direction': 'BULLISH'},
                },
            },
            {
                'confidence_label': 'LOW',
                'resolved_as': 'LOSS',
                'actual_move': -1.5,
                'signal_stack': {
                    'signal_type': 'test_signal',
                    'prediction_horizon': 'swing_5d',
                    'broker_consensus': {'agreement_direction': 'BEARISH'},
                },
            },
        ]

        for idx, case in enumerate(cases):
            prediction_id = upsert_prediction({
                'prediction_id': f'mm:test_learning_{idx}',
                'ticker': TEST_TICKER,
                'timestamp': f'2026-05-29T12:00:{idx:02d}+00:00',
                'source': 'learning_test',
                'direction': 'BUY',
                'confidence_label': case['confidence_label'],
                'signal_stack': case['signal_stack'],
            })
            if not prediction_id:
                return _fail(f'upsert_prediction failed for case {idx}')
            prediction_ids.append(prediction_id)
            if not upsert_outcome({
                'prediction_id': prediction_id,
                'holding_period': TEST_HOLDING,
                'resolved_as': case['resolved_as'],
                'actual_move': case['actual_move'],
            }):
                return _fail(f'upsert_outcome failed for case {idx}')

        unresolved_id = upsert_prediction({
            'prediction_id': 'mm:test_learning_unresolved',
            'ticker': TEST_TICKER,
            'timestamp': '2026-05-29T12:00:10+00:00',
            'source': 'learning_test',
            'direction': 'BUY',
            'confidence_label': 'MEDIUM',
            'signal_stack': {'signal_type': 'test_signal', 'prediction_horizon': 'intraday'},
        })
        if not unresolved_id:
            return _fail('upsert_prediction failed for unresolved case')
        prediction_ids.append(unresolved_id)

        summary = get_learning_summary()
        overall = summary.get('overall') or {}

        test_rows = [
            row for row in _fetch_test_rows(get_connection(), prediction_ids[:-1])
        ]
        wins = sum(1 for row in test_rows if row['resolved_as'] == 'WIN')
        losses = sum(1 for row in test_rows if row['resolved_as'] == 'LOSS')
        if wins != 2 or losses != 1:
            return _fail(f'unexpected synthetic win/loss counts: wins={wins}, losses={losses}')

        expected_rate = round(2 / 3, 4)
        grouped = get_grouped_performance('confidence')
        if not grouped.get('ok'):
            return _fail('get_grouped_performance returned not ok')

        high_group = next((g for g in grouped.get('groups', []) if g.get('key') == 'HIGH'), None)
        if high_group is None:
            return _fail('HIGH confidence group missing from grouped performance')

        if high_group.get('wins', 0) < 2:
            return _fail('group-by confidence did not include synthetic HIGH wins')

        conn = get_connection()
        try:
            scoped = conn.execute(
                """
                SELECT o.resolved_as
                FROM outcomes o
                JOIN predictions p ON p.prediction_id = o.prediction_id
                WHERE p.ticker = ? AND p.source = 'learning_test'
                """,
                (TEST_TICKER,),
            ).fetchall()
        finally:
            conn.close()

        scoped_wins = sum(1 for row in scoped if row['resolved_as'] == 'WIN')
        scoped_losses = sum(1 for row in scoped if row['resolved_as'] == 'LOSS')
        scoped_rate = round(scoped_wins / (scoped_wins + scoped_losses), 4)
        if scoped_rate != expected_rate:
            return _fail(f'expected win rate {expected_rate}, got {scoped_rate}')

        if overall.get('total_predictions', 0) < 1:
            return _fail('learning summary overall missing total_predictions')

    finally:
        conn = get_connection()
        try:
            _cleanup(conn, prediction_ids)
        finally:
            conn.close()

    print('MARKET_MEMORY_LEARNING_OK')
    return 0


def _fetch_test_rows(conn, prediction_ids: list[str]) -> list[dict]:
    rows = []
    for prediction_id in prediction_ids:
        row = conn.execute(
            """
            SELECT p.prediction_id, o.resolved_as
            FROM predictions p
            JOIN outcomes o ON p.prediction_id = o.prediction_id
            WHERE p.prediction_id = ?
            """,
            (prediction_id,),
        ).fetchone()
        if row is not None:
            rows.append(dict(row))
    return rows


if __name__ == '__main__':
    raise SystemExit(main())
