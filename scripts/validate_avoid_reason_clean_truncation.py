#!/usr/bin/env python3
"""Validate Stage 50L avoid reason truncation."""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)


def _fail(msg: str) -> int:
    print(f'AVOID_REASON_CLEAN_TRUNCATION_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    src = (PROJECT_ROOT / 'backend/telegram/response_format.py').read_text(encoding='utf-8')
    if 'clean_avoid_reason_text' not in src:
        return _fail('response_format missing clean_avoid_reason_text')
    proc = os.system(f'{sys.executable} scripts/test_avoid_reason_clean_truncation.py')
    if proc != 0:
        return _fail('test_avoid_reason_clean_truncation.py failed')
    print('AVOID_REASON_CLEAN_TRUNCATION_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
