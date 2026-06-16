#!/usr/bin/env python3
"""Validate Stage 50Q today no stale candidate test."""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)


def _fail(msg: str) -> int:
    print(f'TODAY_NO_STALE_CANDIDATE_WHEN_SCANNER_FRESH_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    proc = os.system(f'{sys.executable} scripts/test_today_no_stale_candidate_when_scanner_fresh.py')
    if proc != 0:
        return _fail('test_today_no_stale_candidate_when_scanner_fresh.py failed')
    print('TODAY_NO_STALE_CANDIDATE_WHEN_SCANNER_FRESH_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
