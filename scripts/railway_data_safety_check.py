#!/usr/bin/env python3
"""
Railway data safety check (Stage 46E).

Usage:
  python scripts/railway_data_safety_check.py

Prints RAILWAY_DATA_SAFETY_OK on success.
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


def _fail(msg: str) -> int:
    print(f'RAILWAY_DATA_SAFETY_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    os.environ.setdefault('APP_MODE', 'railway')
    os.environ.setdefault('RAILWAY_DATA_DIR', '/app/data')

    from backend.storage.data_paths import (
        PROTECTED_DB_NAMES,
        ensure_data_root_safe,
        get_data_root,
        is_railway_data_mode,
        log_data_startup,
    )

    if not is_railway_data_mode():
        return _fail('expected Railway data mode')

    root = get_data_root()
    if root.as_posix() != '/app/data':
        return _fail(f'data root must be /app/data, got {root.as_posix()}')

    safe_root = ensure_data_root_safe()
    if not safe_root.is_dir():
        return _fail('data root is not a directory')

    backups = safe_root / 'backups'
    backups.mkdir(parents=True, exist_ok=True)
    if not backups.is_dir():
        return _fail('backups path could not be created')

    probe = backups / '.write_probe'
    try:
        probe.write_text('ok', encoding='utf-8')
        probe.unlink(missing_ok=True)
    except OSError as exc:
        return _fail(f'volume path not writable: {exc}')

    for name in PROTECTED_DB_NAMES:
        db_path = safe_root / name
        if db_path.is_file():
            size_before = db_path.stat().st_size
            ensure_data_root_safe()
            if not db_path.is_file() or db_path.stat().st_size != size_before:
                return _fail(f'existing DB was modified: {name}')

    log_data_startup()
    print('RAILWAY_DATA_SAFETY_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
