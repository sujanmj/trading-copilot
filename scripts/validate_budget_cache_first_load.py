#!/usr/bin/env python3
"""Validate Budget cache-first load (Stage 48D)."""

from __future__ import annotations

import os
import sys


def main() -> int:
    if os.system(f'{sys.executable} scripts/test_budget_cache_first_load.py') != 0:
        print('BUDGET_CACHE_FIRST_LOAD_FAIL: test failed', file=sys.stderr)
        return 1
    print('BUDGET_CACHE_FIRST_LOAD_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
