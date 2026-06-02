#!/usr/bin/env python3
"""
Validate Railway data safety pack (Stage 46E).

Usage:
  python scripts/validate_railway_data_safety.py

Prints RAILWAY_DATA_SAFETY_OK on success.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if str(Path.cwd().resolve()) != str(PROJECT_ROOT.resolve()):
    os.chdir(PROJECT_ROOT)

STAGE_MARKER = 'RAILWAY_STAGE_46E_DATA_SAFETY'

REQUIRED_FILES = (
    'backend/storage/data_paths.py',
    'scripts/railway_data_safety_check.py',
    'scripts/test_railway_data_safety.py',
    'scripts/validate_railway_data_safety.py',
)


def _fail(msg: str) -> int:
    print(f'RAILWAY_DATA_SAFETY_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    for rel in REQUIRED_FILES:
        if not (PROJECT_ROOT / rel).is_file():
            return _fail(f'missing file: {rel}')

    helper = (PROJECT_ROOT / 'backend/storage/data_paths.py').read_text(encoding='utf-8')
    for fragment in (
        'DEFAULT_RAILWAY_DATA_DIR',
        'is_railway_data_mode',
        'ensure_data_root_safe',
        'data_preserved',
        'log_data_startup',
        'PROTECTED_DB_NAMES',
        '[DATA_ROOT]',
        '[DATA_PRESERVE]',
    ):
        if fragment not in helper:
            return _fail(f'data_paths missing: {fragment}')

    proc = subprocess.run(
        [sys.executable, 'scripts/test_railway_data_safety.py'],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if proc.returncode != 0:
        return _fail(proc.stderr or proc.stdout)
    if 'RAILWAY_DATA_SAFETY_TEST_OK' not in proc.stdout:
        return _fail('test script missing RAILWAY_DATA_SAFETY_TEST_OK')

    print(STAGE_MARKER)
    print('RAILWAY_DATA_SAFETY_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
