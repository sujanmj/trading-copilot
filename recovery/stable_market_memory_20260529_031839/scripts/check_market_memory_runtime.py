#!/usr/bin/env python3
"""
Read canonical market memory DB for runtime visibility.

Usage:
  python scripts/check_market_memory_runtime.py

Prints stats, latest predictions, latest context snapshots.
Prints exactly MARKET_MEMORY_RUNTIME_OK when the DB is readable.
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
    print(f'MARKET_MEMORY_RUNTIME_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.storage.market_memory_db import get_connection, get_market_memory_stats

    try:
        stats = get_market_memory_stats()
    except Exception as exc:
        return _fail(f'get_market_memory_stats failed: {exc}')

    print('[RUNTIME] stats=' + json.dumps(stats, default=str))

    if not stats.get('db_exists'):
        return _fail(f'database missing: {stats.get("db_path")}')

    try:
        conn = get_connection()
        try:
            preds = conn.execute(
                """
                SELECT prediction_id, ticker, timestamp, source, direction, confidence
                FROM predictions
                ORDER BY timestamp DESC
                LIMIT 5
                """
            ).fetchall()
            contexts = conn.execute(
                """
                SELECT context_id, timestamp, market_regime, vix, crude
                FROM market_context_snapshots
                ORDER BY timestamp DESC
                LIMIT 5
                """
            ).fetchall()
        finally:
            conn.close()
    except Exception as exc:
        return _fail(f'database read failed: {exc}')

    print('[RUNTIME] latest_predictions=' + json.dumps([dict(row) for row in preds], default=str))
    print('[RUNTIME] latest_context=' + json.dumps([dict(row) for row in contexts], default=str))

    print('MARKET_MEMORY_RUNTIME_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
