#!/usr/bin/env python3
"""Validate Stage 50P today live scanner priority test."""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)


def _fail(msg: str) -> int:
    print(f'TODAY_USES_LIVE_SCANNER_OVER_STALE_REPORT_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    proc = os.system(f'{sys.executable} scripts/test_today_uses_live_scanner_over_stale_report.py')
    if proc != 0:
        return _fail('test_today_uses_live_scanner_over_stale_report.py failed')
    print('TODAY_USES_LIVE_SCANNER_OVER_STALE_REPORT_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
