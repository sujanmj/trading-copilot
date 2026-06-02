#!/usr/bin/env python3
"""
Initialize historical market memory SQLite DB.

Usage:
  python scripts/init_historical_market_memory.py
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


def main() -> int:
    from backend.storage.historical_market_store import (
        get_historical_db_path,
        get_stats,
        init_db,
    )

    ok = init_db()
    path = get_historical_db_path()
    stats = get_stats()

    print(f'[init_historical_market_memory] path={path}')
    print(f'[init_historical_market_memory] stats={json.dumps(stats, default=str)}')
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
