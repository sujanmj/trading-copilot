#!/usr/bin/env python3
"""Validate budget cache indexes (Stage 48G)."""

from __future__ import annotations

import os
import sys


def main() -> int:
    if os.system(f'{sys.executable} scripts/test_budget_cache_indexes.py') != 0:
        print('BUDGET_CACHE_INDEXES_FAIL: test failed', file=sys.stderr)
        return 1
    print('BUDGET_CACHE_INDEXES_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
