#!/usr/bin/env python3
"""
Smoke test for daily_startup_check.py.

Usage:
  python scripts/test_daily_startup_check.py

Prints exactly DAILY_STARTUP_CHECK_OK on success.
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


def _fail(msg: str) -> int:
    print(f'DAILY_STARTUP_CHECK_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from scripts.daily_startup_check import run_daily_startup_check

    result = run_daily_startup_check(skip_api=True)
    required = (
        'local_safety',
        'market_memory',
        'historical_memory',
        'price_coverage',
        'final_confidence',
        'market_router',
        'scheduler',
        'api',
        'backup',
    )
    for name in required:
        if name not in result.sections:
            return _fail(f'missing section: {name}')

    if result.sections.get('local_safety') == 'fail':
        return _fail('local_safety=fail')

    proc = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / 'scripts' / 'daily_startup_check.py'), '--skip-api'],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=120,
    )
    stdout = proc.stdout or ''
    if proc.returncode not in (0, 1):
        return _fail(f'CLI exit {proc.returncode}: {(proc.stderr or stdout).strip()}')

    if '[DAILY_CHECK] ready=' not in stdout:
        return _fail('CLI missing ready line')
    if not any(
        token in stdout
        for token in (
            'DAILY_STARTUP_READY',
            'DAILY_STARTUP_READY_WITH_WARNINGS',
            'DAILY_STARTUP_NOT_READY',
        )
    ):
        return _fail('CLI missing verdict token')

    print('DAILY_STARTUP_CHECK_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
