#!/usr/bin/env python3
"""
Validate wrapper for local system readiness gate.

Usage:
  python scripts/validate_local_system_readiness.py

Runs local_system_readiness.py and prints LOCAL_SYSTEM_READINESS_VALIDATE_OK on success.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = PROJECT_ROOT / 'scripts' / 'local_system_readiness.py'


def _fail(msg: str) -> int:
    print(f'LOCAL_SYSTEM_READINESS_VALIDATE_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    if not SCRIPT.is_file():
        return _fail(f'missing {SCRIPT.name}')

    proc = subprocess.run(
        [sys.executable, str(SCRIPT), '--continue-on-fail'],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=600,
    )
    combined = (proc.stdout or '') + (proc.stderr or '')
    if proc.returncode != 0:
        tail = combined.strip().splitlines()[-3:] if combined.strip() else [f'exit {proc.returncode}']
        return _fail(' | '.join(tail))

    if 'LOCAL_SYSTEM_READY' not in combined:
        return _fail('missing LOCAL_SYSTEM_READY token')
    if '[LOCAL_READY] ready=True' not in combined:
        return _fail('ready != True')

    print('LOCAL_SYSTEM_READINESS_VALIDATE_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
