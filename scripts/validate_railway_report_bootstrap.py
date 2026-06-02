#!/usr/bin/env python3
"""
Validate Railway report bootstrap pack (Stage 46F).

Usage:
  python scripts/validate_railway_report_bootstrap.py

Prints RAILWAY_REPORT_BOOTSTRAP_OK on success.
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

STAGE_MARKER = 'RAILWAY_STAGE_46F_REPORT_BOOTSTRAP'


def _fail(msg: str) -> int:
    print(f'RAILWAY_REPORT_BOOTSTRAP_VALIDATE_FAIL: {msg}', file=sys.stderr)
    return 1


def _run_test_script() -> str | None:
    proc = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / 'scripts/test_railway_report_bootstrap.py')],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if proc.returncode != 0:
        return proc.stderr or proc.stdout or 'test script failed'
    if 'RAILWAY_REPORT_BOOTSTRAP_TEST_OK' not in proc.stdout:
        return 'test script missing RAILWAY_REPORT_BOOTSTRAP_TEST_OK'
    return None


def main() -> int:
    err = _run_test_script()
    if err:
        return _fail(err)

    print(STAGE_MARKER)
    print('RAILWAY_REPORT_BOOTSTRAP_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
