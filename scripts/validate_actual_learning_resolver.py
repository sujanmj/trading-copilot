#!/usr/bin/env python3
"""Validate Phase 4A Actual Learning Resolver."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    cmd = [sys.executable, str(PROJECT_ROOT / 'scripts' / 'test_actual_learning_resolver.py')]
    proc = subprocess.run(cmd, cwd=PROJECT_ROOT, text=True, capture_output=True, timeout=120)
    if proc.stdout:
        print(proc.stdout, end='')
    if proc.stderr:
        print(proc.stderr, end='', file=sys.stderr)
    if proc.returncode != 0:
        print('ACTUAL_LEARNING_RESOLVER_FAIL', file=sys.stderr)
        return proc.returncode
    if 'ACTUAL_LEARNING_RESOLVER_TEST_OK' not in proc.stdout:
        print('ACTUAL_LEARNING_RESOLVER_FAIL: missing test OK marker', file=sys.stderr)
        return 1
    print('ACTUAL_LEARNING_RESOLVER_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
