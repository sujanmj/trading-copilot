#!/usr/bin/env python3
"""
Validate Railway Telegram handler selection (Stage 46D).

Usage:
  python scripts/validate_railway_telegram_handler_selection.py

Prints RAILWAY_TELEGRAM_HANDLER_SELECTION_OK on success.
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

STAGE_MARKER = 'RAILWAY_STAGE_46D_TELEGRAM_HANDLER'

REQUIRED_FILES = (
    'backend/config/local_safe_mode.py',
    'backend/api/api_server.py',
    'backend/telegram/telegram_analysis_bot.py',
    'scripts/run_railway_web.py',
    'scripts/run_railway_telegram_worker.py',
    'scripts/test_railway_telegram_handler_selection.py',
    'scripts/validate_railway_telegram_handler_selection.py',
)


def _fail(msg: str) -> int:
    print(f'RAILWAY_TELEGRAM_HANDLER_SELECTION_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    for rel in REQUIRED_FILES:
        if not (PROJECT_ROOT / rel).is_file():
            return _fail(f'missing file: {rel}')

    helper = (PROJECT_ROOT / 'backend/config/local_safe_mode.py').read_text(encoding='utf-8')
    for fragment in (
        STAGE_MARKER,
        'apply_railway_telegram_defaults',
        'DISABLE_LEGACY_TELEGRAM_LISTENER',
        'is_legacy_telegram_listener_disabled',
        'ASTRAEDGE_TELEGRAM_BUILD',
    ):
        if fragment not in helper:
            return _fail(f'local_safe_mode missing: {fragment}')

    config_src = (PROJECT_ROOT / 'backend/utils/config.py').read_text(encoding='utf-8')
    if 'DISABLE_LEGACY_TELEGRAM_LISTENER' not in config_src:
        return _fail('config.py missing DISABLE_LEGACY_TELEGRAM_LISTENER')

    api_src = (PROJECT_ROOT / 'backend/api/api_server.py').read_text(encoding='utf-8')
    for fragment in (
        '/api/debug/build-info',
        'astraedge_analysis_bot',
        'LEGACY_TELEGRAM_LISTENER_DISABLED',
    ):
        if fragment not in api_src:
            return _fail(f'api_server missing: {fragment}')

    bot_src = (PROJECT_ROOT / 'backend/telegram/telegram_analysis_bot.py').read_text(encoding='utf-8')
    if '🤖 AstraEdge Telegram' not in bot_src:
        return _fail('telegram_analysis_bot missing AstraEdge help header')

    status_src = (PROJECT_ROOT / 'backend/telegram/response_format.py').read_text(encoding='utf-8')
    if 'AstraEdge 46D' not in status_src:
        return _fail('response_format missing AstraEdge 46D build line')

    proc = subprocess.run(
        [sys.executable, 'scripts/test_railway_telegram_handler_selection.py'],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if proc.returncode != 0:
        return _fail(f'test script failed: {proc.stderr or proc.stdout}')
    if 'RAILWAY_TELEGRAM_HANDLER_SELECTION_TEST_OK' not in proc.stdout:
        return _fail('test script missing RAILWAY_TELEGRAM_HANDLER_SELECTION_TEST_OK')

    print('RAILWAY_TELEGRAM_HANDLER_SELECTION_OK')
    print(f'marker={STAGE_MARKER}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
