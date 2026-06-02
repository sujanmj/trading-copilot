#!/usr/bin/env python3
"""
Smoke test for runtime snapshot auto-capture into canonical_market_memory.db.

Usage:
  python scripts/test_runtime_snapshot_auto_capture.py

Prints exactly RUNTIME_SNAPSHOT_AUTO_CAPTURE_OK on success.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if str(Path.cwd().resolve()) != str(PROJECT_ROOT.resolve()):
    os.chdir(PROJECT_ROOT)

os.environ.setdefault('ENABLE_MARKET_MEMORY_AUTO_CAPTURE', 'true')
os.environ.setdefault('ENABLE_MARKET_MEMORY_CAPTURE', 'true')

TEST_TICKER_A = '__AUTO_CAPTURE_A__'
TEST_TICKER_B = '__AUTO_CAPTURE_B__'
TEST_TS = '2026-05-29T12:00:00+00:00'


def _fail(msg: str) -> int:
    print(f'RUNTIME_SNAPSHOT_AUTO_CAPTURE_FAIL: {msg}', file=sys.stderr)
    return 1


def _cleanup_rows() -> None:
    from backend.storage.market_memory_db import get_connection

    conn = get_connection()
    try:
        for ticker in (TEST_TICKER_A, TEST_TICKER_B):
            conn.execute('DELETE FROM predictions WHERE ticker = ?', (ticker,))
        conn.commit()
    finally:
        conn.close()


def main() -> int:
    from backend.storage.market_memory_db import get_connection, init_market_memory_db
    from backend.storage.runtime_snapshot_memory_capture import (
        capture_active_predictions_from_snapshot,
    )

    _cleanup_rows()

    if not init_market_memory_db():
        return _fail('init_market_memory_db failed')

    snapshot = {
        'snapshot_published_at': TEST_TS,
        'exports': {
            'active_predictions': {
                'predictions': [
                    {
                        'prediction_id': 99001,
                        'ticker': TEST_TICKER_A,
                        'recommendation': 'BUY',
                        'confidence': 'HIGH',
                    },
                    {
                        'prediction_id': 99002,
                        'symbol': TEST_TICKER_B,
                        'direction': 'BULLISH',
                        'confidence': 'MEDIUM',
                        'timestamp': TEST_TS,
                    },
                ],
            },
        },
    }

    result = capture_active_predictions_from_snapshot(
        snapshot,
        source_name='test_runtime_snapshot_auto_capture',
    )
    if not result.get('ok'):
        return _fail(f'capture failed: {result}')
    if int(result.get('candidates_found') or 0) != 2:
        return _fail(f'expected 2 candidates_found, got {result.get("candidates_found")}')
    if int(result.get('captured') or 0) < 2:
        return _fail(f'expected at least 2 captured, got {result}')

    conn = get_connection()
    try:
        for ticker in (TEST_TICKER_A, TEST_TICKER_B):
            row = conn.execute(
                'SELECT prediction_id, ticker, source FROM predictions WHERE ticker = ?',
                (ticker,),
            ).fetchone()
            if row is None:
                return _fail(f'missing row for {ticker}')
            if row['source'] != 'runtime_snapshot_active_predictions':
                return _fail(f'unexpected source for {ticker}: {row["source"]}')
    finally:
        conn.close()

    _cleanup_rows()

    conn = get_connection()
    try:
        for ticker in (TEST_TICKER_A, TEST_TICKER_B):
            row = conn.execute(
                'SELECT 1 FROM predictions WHERE ticker = ?',
                (ticker,),
            ).fetchone()
            if row is not None:
                return _fail(f'cleanup left row for {ticker}')
    finally:
        conn.close()

    print('RUNTIME_SNAPSHOT_AUTO_CAPTURE_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
