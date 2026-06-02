#!/usr/bin/env python3
"""
Smoke test for run_daily_local_cycle.py dry-run path.

Usage:
  python scripts/test_daily_local_cycle.py

Prints exactly DAILY_LOCAL_CYCLE_TEST_OK on success.
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
    print(f'DAILY_LOCAL_CYCLE_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from scripts.run_daily_local_cycle import run_daily_local_cycle

    ok = run_daily_local_cycle(dry_run=True, skip_api=True, market_aware=True)
    if not ok:
        return _fail('run_daily_local_cycle returned False')

    proc = subprocess.run(
        [
            sys.executable,
            str(PROJECT_ROOT / 'scripts' / 'run_daily_local_cycle.py'),
            '--dry-run',
            '--skip-api',
        ],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=300,
    )
    stdout = proc.stdout or ''
    if proc.returncode != 0:
        return _fail(f'CLI exit {proc.returncode}: {(proc.stderr or stdout).strip()}')
    if 'DAILY_LOCAL_CYCLE_OK' not in stdout:
        return _fail('CLI missing DAILY_LOCAL_CYCLE_OK')

    print('DAILY_LOCAL_CYCLE_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
