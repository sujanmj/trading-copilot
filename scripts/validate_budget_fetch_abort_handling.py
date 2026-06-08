#!/usr/bin/env python3
"""Validate Budget tab fetch abort handling (Stage 48B)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _fail(msg: str) -> int:
    print(f'BUDGET_FETCH_ABORT_HANDLING_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    if os.system(f'{sys.executable} scripts/test_budget_fetch_abort_handling.py') != 0:
        return _fail('test_budget_fetch_abort_handling.py failed')
    print('BUDGET_FETCH_ABORT_HANDLING_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
