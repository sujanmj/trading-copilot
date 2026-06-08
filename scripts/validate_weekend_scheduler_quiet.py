#!/usr/bin/env python3
"""Validate weekend premarket scheduler suppression (Stage 47C)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)


def _fail(msg: str) -> int:
    print(f'WEEKEND_SCHEDULER_QUIET_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    if os.system(f'{sys.executable} scripts/test_weekend_scheduler_quiet.py') != 0:
        return _fail('test_weekend_scheduler_quiet.py failed')
    print('WEEKEND_SCHEDULER_QUIET_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
