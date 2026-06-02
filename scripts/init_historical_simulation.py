#!/usr/bin/env python3
"""
Initialize historical simulation schema in historical_market_memory.db.

Usage:
  python scripts/init_historical_simulation.py

Prints exactly HISTORICAL_SIMULATION_INIT_OK on success.
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


def _fail(msg: str) -> int:
    print(f'HISTORICAL_SIMULATION_INIT_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.storage.historical_market_store import get_historical_db_path, init_db

    if not init_db():
        return _fail('init_db returned False')

    db_path = get_historical_db_path()
    if not db_path.exists():
        return _fail(f'database missing: {db_path}')

    print('HISTORICAL_SIMULATION_INIT_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
