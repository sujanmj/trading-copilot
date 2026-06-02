#!/usr/bin/env python3
"""
Smoke test for legacy prediction cleanup scripts.

Usage:
  python scripts/test_legacy_prediction_cleanup.py

Prints exactly LEGACY_PREDICTION_CLEANUP_OK on success; exits 1 on failure.
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

TEST_TICKER = '__TEST_LEGACY_CLEANUP__'
SAFE_LEGACY_ID = 'legacy:999001'
BLOCKED_LEGACY_ID = 'legacy:999002'
TEST_HOLDING = 'test_legacy_cleanup'
TEST_SOURCE = 'legacy_cleanup_test'


def _fail(msg: str) -> int:
    print(f'LEGACY_PREDICTION_CLEANUP_FAIL: {msg}', file=sys.stderr)
    return 1


def _base_payload(*, legacy_id: str, legacy_prediction_id: int) -> dict:
    return {
        'ticker': TEST_TICKER,
        'timestamp': '2026-01-01T00:00:00+00:00',
        'source': TEST_SOURCE,
        'direction': 'BULLISH',
        'confidence': 0.5,
        'reasoning': 'synthetic legacy cleanup test',
        'legacy_prediction_id': legacy_prediction_id,
        'signal_stack': {'prediction_horizon': 'intraday'},
        'raw_payload': {
            'id': legacy_prediction_id,
            'prediction_date': '2026-01-01',
            'prediction_horizon': 'intraday',
            'run_type': 'test',
        },
        'prediction_id': legacy_id,
    }


def _cleanup(conn, *, mm_id: str | None = None) -> None:
    for legacy_id in (SAFE_LEGACY_ID, BLOCKED_LEGACY_ID):
        conn.execute(
            'DELETE FROM outcomes WHERE prediction_id = ?',
            (legacy_id,),
        )
        conn.execute(
            'DELETE FROM predictions WHERE prediction_id = ?',
            (legacy_id,),
        )
    if mm_id:
        conn.execute('DELETE FROM predictions WHERE prediction_id = ?', (mm_id,))
    conn.commit()


def main() -> int:
    from backend.storage.market_memory_db import (
        get_connection,
        init_market_memory_db,
        make_canonical_prediction_id,
        upsert_prediction,
        upsert_outcome,
    )
    from scripts.delete_legacy_market_memory_predictions import delete_legacy_market_memory_predictions

    if not init_market_memory_db():
        return _fail('init_market_memory_db returned False')

    safe_payload = _base_payload(legacy_id=SAFE_LEGACY_ID, legacy_prediction_id=999001)
    blocked_payload = _base_payload(legacy_id=BLOCKED_LEGACY_ID, legacy_prediction_id=999002)
    safe_mm_id = make_canonical_prediction_id(safe_payload)
    blocked_mm_id = make_canonical_prediction_id(blocked_payload)

    conn = get_connection()
    try:
        _cleanup(conn, mm_id=safe_mm_id)
        _cleanup(conn, mm_id=blocked_mm_id)

        upsert_prediction(safe_payload)
        upsert_prediction({**safe_payload, 'prediction_id': safe_mm_id})

        upsert_prediction(blocked_payload)
        upsert_prediction({**blocked_payload, 'prediction_id': blocked_mm_id})
        upsert_outcome({
            'prediction_id': BLOCKED_LEGACY_ID,
            'holding_period': TEST_HOLDING,
            'resolved_as': 'WIN',
            'actual_move': 1.0,
        })

        test_ids = {SAFE_LEGACY_ID, BLOCKED_LEGACY_ID}

        dry_summary = delete_legacy_market_memory_predictions(
            confirm=False,
            only_prediction_ids=test_ids,
        )
        if dry_summary.get('deleted', 0) != 0:
            return _fail(f'dry-run deleted rows: {dry_summary.get("deleted")}')
        if not dry_summary.get('dry_run'):
            return _fail('dry-run summary dry_run flag is False')
        if dry_summary.get('safe_to_delete') != 1:
            return _fail(
                f'dry-run safe_to_delete={dry_summary.get("safe_to_delete")}, expected 1',
            )

        safe_row = conn.execute(
            'SELECT 1 FROM predictions WHERE prediction_id = ?',
            (SAFE_LEGACY_ID,),
        ).fetchone()
        blocked_row = conn.execute(
            'SELECT 1 FROM predictions WHERE prediction_id = ?',
            (BLOCKED_LEGACY_ID,),
        ).fetchone()
        if safe_row is None or blocked_row is None:
            return _fail('test legacy rows missing after dry-run')

        confirm_summary = delete_legacy_market_memory_predictions(
            confirm=True,
            only_prediction_ids=test_ids,
        )
        if confirm_summary.get('deleted') != 1:
            return _fail(
                f'--confirm deleted {confirm_summary.get("deleted")} rows, expected 1',
            )
        if confirm_summary.get('blocked_outcome_refs') != 1:
            return _fail(
                f'blocked_outcome_refs={confirm_summary.get("blocked_outcome_refs")}, expected 1',
            )

        safe_row = conn.execute(
            'SELECT 1 FROM predictions WHERE prediction_id = ?',
            (SAFE_LEGACY_ID,),
        ).fetchone()
        blocked_row = conn.execute(
            'SELECT 1 FROM predictions WHERE prediction_id = ?',
            (BLOCKED_LEGACY_ID,),
        ).fetchone()
        if safe_row is not None:
            return _fail('safe legacy row still present after --confirm')
        if blocked_row is None:
            return _fail('blocked legacy row was deleted after --confirm')

        mm_row = conn.execute(
            'SELECT 1 FROM predictions WHERE prediction_id = ?',
            (safe_mm_id,),
        ).fetchone()
        if mm_row is None:
            return _fail('mm copy was deleted')

        _cleanup(conn, mm_id=safe_mm_id)
        _cleanup(conn, mm_id=blocked_mm_id)
        conn.execute(
            'DELETE FROM outcomes WHERE prediction_id = ? AND holding_period = ?',
            (BLOCKED_LEGACY_ID, TEST_HOLDING),
        )
        conn.commit()
    finally:
        conn.close()

    print('LEGACY_PREDICTION_CLEANUP_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
