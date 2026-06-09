#!/usr/bin/env python3
"""Unit tests — outcome store data root consistency (Stage 49D)."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)


def _fail(msg: str) -> int:
    print(f'OUTCOME_STORE_DATA_ROOT_CONSISTENCY_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.storage.data_paths import get_data_path, get_data_root
    from backend.storage.market_memory_db import get_market_memory_path
    from backend.storage.outcome_resolver import (
        get_canonical_outcome_stats,
        get_memory_dashboard_cache_path,
        get_outcome_resolver_state_path,
        get_outcome_resolver_status,
    )
    from backend.telegram.lazy_command_runner import MEMORY_CACHE_FILE

    with patch.dict(os.environ, {'RAILWAY_DATA_DIR': '/app/data'}, clear=False):
        root = get_data_root()
        if root.as_posix() != '/app/data':
            return _fail(f'expected /app/data got {root.as_posix()}')

        db_path = get_market_memory_path()
        state_path = get_outcome_resolver_state_path()
        cache_path = get_memory_dashboard_cache_path()
        data_path = get_data_path('canonical_market_memory.db')

        if db_path != data_path:
            return _fail('market_memory_db and get_data_path must match')
        if db_path.parent != root:
            return _fail('market memory DB must live under data root')
        if state_path.parent != root:
            return _fail('resolver state must live under data root')
        if cache_path.parent != root:
            return _fail('memory dashboard cache must live under data root')

        with patch('backend.storage.data_paths.get_data_root', return_value=root):
            status = get_outcome_resolver_status()
        if status.get('data_root') != '/app/data':
            return _fail(f'get_outcome_resolver_status missing data_root got {status!r}')

        with patch('backend.storage.data_paths.get_data_root', return_value=root):
            stats = get_canonical_outcome_stats()
        if stats.get('data_root') != '/app/data':
            return _fail(f'get_canonical_outcome_stats missing data_root got {stats!r}')

    local_root = PROJECT_ROOT / 'data'
    with patch.dict(os.environ, {}, clear=True):
        os.environ.pop('RAILWAY_DATA_DIR', None)
        os.environ.pop('RAILWAY_ENVIRONMENT', None)
        os.environ.pop('APP_MODE', None)
        root = get_data_root()
        if root.resolve() != local_root.resolve():
            return _fail(f'local data root expected {local_root} got {root}')

    if MEMORY_CACHE_FILE.parent.resolve() != get_data_root().resolve():
        return _fail('lazy_command_runner MEMORY_CACHE_FILE must use canonical data root')

    print('OUTCOME_STORE_DATA_ROOT_CONSISTENCY_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
