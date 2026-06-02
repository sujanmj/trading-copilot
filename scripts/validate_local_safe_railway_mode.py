#!/usr/bin/env python3
"""
Validate local safe mode vs Railway control plane (Stage 46C).

Usage:
  python scripts/validate_local_safe_railway_mode.py

Prints LOCAL_SAFE_RAILWAY_MODE_OK on success.
Marker: LOCAL_STAGE_46C_SAFE_RAILWAY_CONTROL
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

REQUIRED_FILES = (
    'backend/config/local_safe_mode.py',
    'backend/utils/telegram_guard.py',
    'scripts/run_telegram_analysis_bot.py',
    'scripts/test_local_safe_railway_mode.py',
    'scripts/validate_local_safe_railway_mode.py',
    'docs/LOCAL_SAFE_RAILWAY_CONTROL.md',
)


def _fail(msg: str) -> int:
    print(f'LOCAL_SAFE_RAILWAY_MODE_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    for rel in REQUIRED_FILES:
        if not (PROJECT_ROOT / rel).is_file():
            return _fail(f'missing file: {rel}')

    helper = (PROJECT_ROOT / 'backend/config/local_safe_mode.py').read_text(encoding='utf-8')
    for fragment in (
        STAGE_MARKER,
        'apply_local_safe_mode_defaults',
        'is_railway_mode',
        'ALLOW_LOCAL_TELEGRAM',
        'ALLOW_LOCAL_TELEGRAM_SENDS',
        'LOCAL_TELEGRAM_DISABLED_RAILWAY_IS_LIVE',
        'LOCAL_TELEGRAM_SENDS_DRY_RUN',
        'DISABLE_TRADE_EXECUTION',
    ):
        if fragment not in helper:
            return _fail(f'local_safe_mode missing: {fragment}')

    runner = (PROJECT_ROOT / 'scripts/run_telegram_analysis_bot.py').read_text(encoding='utf-8')
    for fragment in (
        'apply_local_safe_mode_defaults',
        'LOCAL_TELEGRAM_DISABLED_MSG',
        'local_telegram_runner_blocked',
    ):
        if fragment not in runner:
            return _fail(f'run_telegram_analysis_bot missing: {fragment}')

    guard = (PROJECT_ROOT / 'backend/utils/telegram_guard.py').read_text(encoding='utf-8')
    for fragment in ('telegram_send_dry_run', 'LOCAL_TELEGRAM_SENDS_DRY_RUN', 'guard_telegram_send'):
        if fragment not in guard:
            return _fail(f'telegram_guard missing: {fragment}')

    for rel in (
        'scripts/send_telegram_morning_brief.py',
        'scripts/send_telegram_market_close_summary.py',
        'scripts/send_telegram_overnight_brief.py',
    ):
        src = (PROJECT_ROOT / rel).read_text(encoding='utf-8')
        if 'apply_local_safe_mode_defaults' not in src:
            return _fail(f'{rel} missing apply_local_safe_mode_defaults')

    railway_worker = (PROJECT_ROOT / 'scripts/run_railway_telegram_worker.py').read_text(encoding='utf-8')
    if "APP_MODE': 'railway'" not in railway_worker and 'APP_MODE' not in railway_worker:
        return _fail('run_railway_telegram_worker missing railway APP_MODE')

    cors_src = (PROJECT_ROOT / 'backend/api/api_server.py').read_text(encoding='utf-8')
    if 'ALLOWED_ORIGINS' not in cors_src:
        return _fail('api_server missing ALLOWED_ORIGINS CORS support')
    if 'http://127.0.0.1:5173' not in cors_src:
        return _fail('api_server missing localhost:5173 CORS origin')

    doc = (PROJECT_ROOT / 'docs/LOCAL_SAFE_RAILWAY_CONTROL.md').read_text(encoding='utf-8')
    for fragment in (
        STAGE_MARKER,
        'ALLOW_LOCAL_TELEGRAM',
        'ALLOW_LOCAL_TELEGRAM_SENDS',
        'ASTRAEDGE_API_BASE_URL',
        'Railway',
    ):
        if fragment not in doc:
            return _fail(f'doc missing: {fragment}')

    proc = subprocess.run(
        [sys.executable, 'scripts/test_local_safe_railway_mode.py'],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if proc.returncode != 0:
        return _fail(f'test_local_safe_railway_mode failed: {proc.stderr or proc.stdout}')
    if 'LOCAL_SAFE_RAILWAY_MODE_TEST_OK' not in proc.stdout:
        return _fail('test script missing LOCAL_SAFE_RAILWAY_MODE_TEST_OK')

    print('LOCAL_SAFE_RAILWAY_MODE_OK')
    print(f'marker={STAGE_MARKER}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
