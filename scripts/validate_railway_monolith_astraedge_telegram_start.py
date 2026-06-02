#!/usr/bin/env python3
"""
Validate Railway monolith AstraEdge Telegram start pack (Stage 46E).

Usage:
  python scripts/validate_railway_monolith_astraedge_telegram_start.py

Prints RAILWAY_MONOLITH_ASTRAEDGE_TELEGRAM_START_OK on success.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if str(Path.cwd().resolve()) != str(PROJECT_ROOT.resolve()):
    import os
    os.chdir(PROJECT_ROOT)

STAGE_MARKER = 'RAILWAY_STAGE_46E_MONOLITH_TELEGRAM'

REQUIRED_FILES = (
    'scripts/run_railway_web.py',
    'backend/telegram/telegram_analysis_bot.py',
    'backend/api/api_server.py',
    'scripts/test_railway_monolith_astraedge_telegram_start.py',
    'scripts/validate_railway_monolith_astraedge_telegram_start.py',
)


def _fail(msg: str) -> int:
    print(f'RAILWAY_MONOLITH_ASTRAEDGE_TELEGRAM_START_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    for rel in REQUIRED_FILES:
        if not (PROJECT_ROOT / rel).is_file():
            return _fail(f'missing file: {rel}')

    bot_src = (PROJECT_ROOT / 'backend/telegram/telegram_analysis_bot.py').read_text(encoding='utf-8')
    for fragment in (
        'ensure_astraedge_telegram_started',
        'should_start_astraedge_telegram',
        'is_astraedge_telegram_started',
        'ASTRAEDGE_TELEGRAM_ANALYSIS_BOT_STARTED',
        'ASTRAEDGE_TELEGRAM_ANALYSIS_BOT_STARTED_DRY_RUN',
        'is_railway_telegram_start_dry_run',
    ):
        if fragment not in bot_src:
            return _fail(f'telegram_analysis_bot missing: {fragment}')

    proc = subprocess.run(
        [sys.executable, 'scripts/test_railway_monolith_astraedge_telegram_start.py'],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if proc.returncode != 0:
        return _fail(proc.stderr or proc.stdout)
    if 'RAILWAY_MONOLITH_ASTRAEDGE_TELEGRAM_START_TEST_OK' not in proc.stdout:
        return _fail('test script missing OK marker')

    print(STAGE_MARKER)
    print('RAILWAY_MONOLITH_ASTRAEDGE_TELEGRAM_START_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
