#!/usr/bin/env python3
"""
Verify trading_history.db and canonical_market_memory.db are strictly isolated.

Usage:
  python scripts/validate_db_routing.py

Prints DB_ROUTING_OK on success; exits 1 on failure.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if str(Path.cwd().resolve()) != str(PROJECT_ROOT.resolve()):
    import os

    os.chdir(PROJECT_ROOT)


def _fail(msg: str) -> int:
    print(f'DB_ROUTING_FAIL: {msg}', file=sys.stderr)
    return 1


def _prediction_columns(db_path: Path) -> set[str]:
    conn = sqlite3.connect(str(db_path))
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='predictions'"
        )
        if not cur.fetchone():
            return set()
        cur.execute('PRAGMA table_info(predictions)')
        return {row[1] for row in cur.fetchall()}
    finally:
        conn.close()


def main() -> int:
    from backend.storage.db_finder import (
        find_predictions_db,
        is_market_memory_db_path,
        is_trading_predictions_schema,
        resolve_db_path,
    )
    from backend.storage.db_manager import get_trading_db_path, init_db
    from backend.storage.market_memory_db import get_market_memory_path

    trading_path = get_trading_db_path()
    market_memory_path = get_market_memory_path()

    if trading_path.name != 'trading_history.db':
        return _fail(f'trading db name must be trading_history.db, got {trading_path.name}')
    if market_memory_path.name != 'canonical_market_memory.db':
        return _fail(
            f'market memory name must be canonical_market_memory.db, got {market_memory_path.name}'
        )
    if trading_path.resolve() == market_memory_path.resolve():
        return _fail('trading and market memory paths must differ')

    if is_market_memory_db_path(trading_path):
        return _fail('trading path classified as market memory')
    if is_market_memory_db_path(resolve_db_path()):
        return _fail('resolve_db_path returned a market memory file')

    found_path, _count = find_predictions_db()
    if found_path and is_market_memory_db_path(found_path):
        return _fail(f'find_predictions_db picked market memory: {found_path}')

    init_db()
    resolved = Path(resolve_db_path())
    if resolved.name == 'canonical_market_memory.db':
        return _fail('resolve_db_path must not return canonical_market_memory.db')
    if not is_trading_predictions_schema(resolved):
        return _fail(f'resolved trading db has wrong schema: {resolved}')

    trading_cols = _prediction_columns(trading_path)
    if 'id' not in trading_cols or 'prediction_date' not in trading_cols:
        return _fail(
            f'trading_history predictions missing legacy columns: {sorted(trading_cols)}'
        )
    if 'prediction_id' in trading_cols and 'id' not in trading_cols:
        return _fail('trading_history.db looks like market memory schema')

    if not market_memory_path.exists():
        return _fail(f'market memory database missing: {market_memory_path}')

    mm_cols = _prediction_columns(market_memory_path)
    if 'prediction_id' not in mm_cols:
        return _fail('canonical_market_memory missing prediction_id column')
    if 'id' in mm_cols and 'prediction_id' not in mm_cols:
        return _fail('canonical_market_memory looks like trading schema')

    mm_conn = sqlite3.connect(str(market_memory_path))
    try:
        row = mm_conn.execute('SELECT COUNT(*) FROM predictions').fetchone()
        mm_count = int(row[0]) if row else 0
    finally:
        mm_conn.close()

    if mm_count < 143:
        return _fail(f'expected at least 143 market memory predictions, got {mm_count}')

    print('DB_ROUTING_OK')
    print(f'trading_db={trading_path}')
    print(f'market_memory_db={market_memory_path}')
    print(f'market_memory_predictions={mm_count}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
