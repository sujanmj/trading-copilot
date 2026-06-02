#!/usr/bin/env python3
"""
Validate historical import safety: UTC compat, fake_prices=0, canonical DB intact.

Usage:
  python scripts/validate_historical_import_safety.py

Prints exactly HISTORICAL_IMPORT_SAFETY_OK on success; exits 1 on failure.
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

IMPORT_SCRIPT = PROJECT_ROOT / 'scripts' / 'import_historical_prices.py'


def _fail(msg: str) -> int:
    print(f'HISTORICAL_IMPORT_SAFETY_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    source = IMPORT_SCRIPT.read_text(encoding='utf-8')
    if 'datetime.UTC' in source:
        return _fail('datetime.UTC found in import_historical_prices.py')
    if 'timezone.utc' not in source:
        return _fail('timezone.utc missing in import_historical_prices.py')

    if 'canonical_market_memory' in source.lower():
        return _fail('import_historical_prices.py must not reference canonical_market_memory.db')

    from backend.storage.historical_market_store import get_connection, get_stats, init_db
    from backend.storage.market_memory_db import (
        get_connection as get_canonical_connection,
        get_market_memory_path,
        get_market_memory_stats,
        init_market_memory_db,
    )

    if not init_db():
        return _fail('historical init_db failed')

    stats = get_stats()
    fake_rows = int(stats.get('fake_prices_rows') or 0)
    if fake_rows != 0:
        return _fail(f'fake_prices_rows={fake_rows}, expected 0')

    conn = get_connection()
    try:
        fake_count = conn.execute(
            'SELECT COUNT(*) AS cnt FROM historical_prices WHERE fake_prices != 0'
        ).fetchone()
        if fake_count and int(fake_count['cnt']) != 0:
            return _fail(f'historical_prices fake_prices != 0 count={fake_count["cnt"]}')
    finally:
        conn.close()

    if not init_market_memory_db():
        return _fail('canonical init_market_memory_db failed')

    canonical_path = get_market_memory_path()
    if not canonical_path.exists():
        return _fail(f'canonical DB missing: {canonical_path}')

    canonical_stats = get_market_memory_stats()
    if not canonical_stats.get('db_exists'):
        return _fail('canonical db_exists is False')

    canonical_conn = get_canonical_connection()
    try:
        tables = {
            row['name']
            for row in canonical_conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        if 'predictions' not in tables:
            return _fail('canonical predictions table missing')
        canonical_conn.execute('SELECT COUNT(*) FROM predictions').fetchone()
    finally:
        canonical_conn.close()

    print('HISTORICAL_IMPORT_SAFETY_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
