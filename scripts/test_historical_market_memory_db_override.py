#!/usr/bin/env python3
"""The 54C validator can isolate historical-memory writes from project data."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    from backend.storage.historical_market_store import get_historical_db_path

    with patch.dict(os.environ, {'ASTRAEDGE_HISTORICAL_MARKET_DB': '/tmp/astraedge-validation.db'}):
        if get_historical_db_path() != Path('/tmp/astraedge-validation.db'):
            raise AssertionError('isolated historical-market DB path was ignored')
    print('HISTORICAL_MARKET_MEMORY_DB_OVERRIDE_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
