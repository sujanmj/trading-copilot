#!/usr/bin/env python3
"""Validate watchdog throttle pack (Stage 46H)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)


def _fail(msg: str) -> int:
    print(f'WATCHDOG_THROTTLE_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    path = PROJECT_ROOT / 'backend/orchestration/watchdog_throttle.py'
    if not path.is_file():
        return _fail('missing watchdog_throttle.py')
    if os.system(f'{sys.executable} scripts/test_watchdog_throttle.py') != 0:
        return _fail('test_watchdog_throttle.py failed')
    print('WATCHDOG_THROTTLE_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
