#!/usr/bin/env python3
"""
Unit tests for local safe mode vs Railway (Stage 46C).

Usage:
  python scripts/test_local_safe_railway_mode.py

Prints LOCAL_SAFE_RAILWAY_MODE_TEST_OK on success.
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

STAGE_MARKER = 'LOCAL_STAGE_46C_SAFE_RAILWAY_CONTROL'
RUNNER = PROJECT_ROOT / 'scripts' / 'run_telegram_analysis_bot.py'


def _fail(msg: str) -> int:
    print(f'LOCAL_SAFE_RAILWAY_MODE_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def _env_truthy(name: str) -> bool:
    return os.environ.get(name, '').strip().lower() in ('1', 'true', 'yes', 'on')


def _fresh_local_env(**overrides: str) -> dict[str, str]:
    env = dict(os.environ)
    for key in (
        'APP_MODE',
        'RAILWAY_ENVIRONMENT',
        'RAILWAY_PROJECT_ID',
        'RAILWAY_SERVICE_NAME',
        'ALLOW_LOCAL_TELEGRAM',
        'ALLOW_LOCAL_TELEGRAM_SENDS',
    ):
        env.pop(key, None)
    env.update(
        {
            'LOCAL_DEV_MODE': '1',
            'LOCAL_ONLY': '1',
            'PYTHONIOENCODING': 'utf-8',
        }
    )
    env.update(overrides)
    return env


def test_local_defaults_disable_listener() -> str | None:
    env = _fresh_local_env()
    env.pop('APP_MODE', None)
    env.pop('RAILWAY_ENVIRONMENT', None)
    proc = subprocess.run(
        [
            sys.executable,
            '-c',
            'import os; '
            'from backend.config.local_safe_mode import apply_local_safe_mode_defaults; '
            'apply_local_safe_mode_defaults(); '
            'from backend.utils.config import DISABLE_TELEGRAM_LISTENER, DISABLE_TELEGRAM_SENDS; '
            'print(int(DISABLE_TELEGRAM_LISTENER), int(DISABLE_TELEGRAM_SENDS))',
        ],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if proc.returncode != 0:
        return f'local defaults subprocess failed: {proc.stderr[:200]}'
    parts = proc.stdout.strip().split()
    if parts != ['1', '1']:
        return f'expected listener=1 sends=1, got {proc.stdout!r}'
    return None


def test_runner_refuses_without_allow_local() -> str | None:
    env = _fresh_local_env()
    proc = subprocess.run(
        [sys.executable, str(RUNNER)],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if proc.returncode == 0:
        return 'run_telegram_analysis_bot should exit non-zero locally without ALLOW_LOCAL_TELEGRAM'
    if 'LOCAL_TELEGRAM_DISABLED_RAILWAY_IS_LIVE' not in proc.stdout + proc.stderr:
        return 'missing LOCAL_TELEGRAM_DISABLED_RAILWAY_IS_LIVE message'
    return None


def test_local_send_dry_run() -> str | None:
    env = _fresh_local_env(
        DISABLE_TELEGRAM='0',
        DISABLE_TELEGRAM_SENDS='0',
    )
    proc = subprocess.run(
        [
            sys.executable,
            '-c',
            'import os; '
            'from backend.config.local_safe_mode import apply_local_safe_mode_defaults; '
            'apply_local_safe_mode_defaults(); '
            'os.environ["DISABLE_TELEGRAM"]="0"; '
            'os.environ["DISABLE_TELEGRAM_SENDS"]="0"; '
            'from backend.utils.telegram_guard import telegram_send_dry_run; '
            'telegram_send_dry_run("test")',
        ],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if 'LOCAL_TELEGRAM_SENDS_DRY_RUN' not in proc.stdout + proc.stderr:
        return 'missing LOCAL_TELEGRAM_SENDS_DRY_RUN'
    return None


def test_railway_mode_no_force_disable() -> str | None:
    env = _fresh_local_env(
        APP_MODE='railway',
        DISABLE_TELEGRAM='0',
        DISABLE_TELEGRAM_LISTENER='0',
        DISABLE_TELEGRAM_SENDS='0',
    )
    proc = subprocess.run(
        [
            sys.executable,
            '-c',
            'from backend.config.local_safe_mode import apply_local_safe_mode_defaults, is_railway_mode; '
            'applied = apply_local_safe_mode_defaults(); '
            'from backend.utils.config import DISABLE_TELEGRAM_LISTENER; '
            'print(int(applied), int(is_railway_mode()), int(DISABLE_TELEGRAM_LISTENER))',
        ],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if proc.returncode != 0:
        return proc.stderr[:200]
    parts = proc.stdout.strip().split()
    if parts != ['0', '1', '0']:
        return f'railway bypass expected 0 1 0, got {proc.stdout!r}'
    return None


def test_trade_execution_disabled_local() -> str | None:
    env = _fresh_local_env()
    proc = subprocess.run(
        [
            sys.executable,
            '-c',
            'from backend.config.local_safe_mode import apply_local_safe_mode_defaults; '
            'apply_local_safe_mode_defaults(); '
            'import os; print(os.environ.get("DISABLE_TRADE_EXECUTION"))',
        ],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if proc.stdout.strip() != '1':
        return f'DISABLE_TRADE_EXECUTION not 1: {proc.stdout!r}'
    return None


def test_stage_marker() -> str | None:
    from backend.config.local_safe_mode import STAGE_MARKER as marker

    if marker != STAGE_MARKER:
        return f'stage marker mismatch: {marker!r}'
    return None


def main() -> int:
    checks = (
        test_stage_marker,
        test_local_defaults_disable_listener,
        test_runner_refuses_without_allow_local,
        test_local_send_dry_run,
        test_railway_mode_no_force_disable,
        test_trade_execution_disabled_local,
    )
    for check in checks:
        err = check()
        if err:
            return _fail(err)
    print('LOCAL_SAFE_RAILWAY_MODE_TEST_OK')
    print(f'marker={STAGE_MARKER}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
