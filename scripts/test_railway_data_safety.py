#!/usr/bin/env python3
"""
Unit tests for Railway data safety (Stage 46E).

Usage:
  python scripts/test_railway_data_safety.py

Prints RAILWAY_DATA_SAFETY_TEST_OK on success.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if str(Path.cwd().resolve()) != str(PROJECT_ROOT.resolve()):
    os.chdir(PROJECT_ROOT)

STAGE_MARKER = 'RAILWAY_STAGE_46E_DATA_SAFETY'

DESTRUCTIVE_PATTERNS = (
    'unlink(trading_history.db',
    'remove(trading_history.db',
    'os.remove(DATA_DIR / "trading_history.db"',
    'DROP TABLE IF EXISTS',
    'shutil.rmtree(get_data_root',
)


def _fail(msg: str) -> int:
    print(f'RAILWAY_DATA_SAFETY_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def _fresh_env(**overrides: str) -> dict[str, str]:
    env = dict(os.environ)
    for key in ('APP_MODE', 'RAILWAY_ENVIRONMENT', 'RAILWAY_DATA_DIR'):
        env.pop(key, None)
    env.update({'PYTHONIOENCODING': 'utf-8'})
    env.update(overrides)
    return env


def test_railway_data_root_app_mode() -> str | None:
    env = _fresh_env(APP_MODE='railway')
    proc = subprocess.run(
        [
            sys.executable,
            '-c',
            'from backend.storage.data_paths import get_data_root; '
            'print(get_data_root().as_posix())',
        ],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if proc.returncode != 0:
        return proc.stderr or proc.stdout
    if proc.stdout.strip() != '/app/data':
        return f'APP_MODE=railway should resolve /app/data, got {proc.stdout.strip()!r}'
    return None


def test_railway_data_root_env_override() -> str | None:
    env = _fresh_env(RAILWAY_DATA_DIR='/custom/data', APP_MODE='railway')
    proc = subprocess.run(
        [
            sys.executable,
            '-c',
            'from backend.storage.data_paths import get_data_root; '
            'print(get_data_root().as_posix())',
        ],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if proc.returncode != 0:
        return proc.stderr or proc.stdout
    if proc.stdout.strip() != '/custom/data':
        return f'RAILWAY_DATA_DIR override failed: {proc.stdout.strip()!r}'
    return None


def test_local_data_root() -> str | None:
    env = _fresh_env()
    proc = subprocess.run(
        [
            sys.executable,
            '-c',
            'from backend.storage.data_paths import get_data_root, PROJECT_ROOT; '
            'print(get_data_root() == PROJECT_ROOT / "data")',
        ],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if proc.returncode != 0 or proc.stdout.strip() != 'True':
        return 'local mode should use repo data/'
    return None


def test_db_preserved() -> str | None:
    with tempfile.TemporaryDirectory() as tmp:
        data_root = Path(tmp) / 'data'
        data_root.mkdir()
        db = data_root / 'trading_history.db'
        db.write_bytes(b'sqlite-test-bytes')
        size_before = db.stat().st_size

        env = _fresh_env(RAILWAY_DATA_DIR=str(data_root))
        proc = subprocess.run(
            [
                sys.executable,
                '-c',
                'from backend.storage.data_paths import ensure_data_root_safe, get_data_path; '
                'ensure_data_root_safe(); '
                'get_data_path("trading_history.db"); '
                'print("ok")',
            ],
            cwd=PROJECT_ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if proc.returncode != 0:
            return proc.stderr or proc.stdout
        if not db.is_file() or db.stat().st_size != size_before:
            return 'existing DB was overwritten or deleted'
    return None


def test_startup_logs() -> str | None:
    src = (PROJECT_ROOT / 'backend/storage/data_paths.py').read_text(encoding='utf-8')
    for fragment in ('[DATA_ROOT]', '[DATA_PRESERVE]', 'log_data_startup'):
        if fragment not in src:
            return f'data_paths missing {fragment}'
    web_src = (PROJECT_ROOT / 'scripts/run_railway_web.py').read_text(encoding='utf-8')
    if 'log_data_startup' not in web_src:
        return 'run_railway_web missing log_data_startup'
    return None


def test_no_destructive_reset() -> str | None:
    data_paths = (PROJECT_ROOT / 'backend/storage/data_paths.py').read_text(encoding='utf-8')
    for pattern in DESTRUCTIVE_PATTERNS:
        if pattern in data_paths:
            return f'destructive pattern in data_paths: {pattern}'
    return None


def main() -> int:
    tests = (
        test_railway_data_root_app_mode,
        test_railway_data_root_env_override,
        test_local_data_root,
        test_db_preserved,
        test_startup_logs,
        test_no_destructive_reset,
    )
    for test_fn in tests:
        err = test_fn()
        if err:
            return _fail(err)

    print(STAGE_MARKER)
    print('RAILWAY_DATA_SAFETY_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
