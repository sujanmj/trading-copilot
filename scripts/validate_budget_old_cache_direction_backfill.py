#!/usr/bin/env python3
"""Validate old budget cache direction backfill (Stage 48H)."""

from __future__ import annotations

import os
import sys


def main() -> int:
    if os.system(f'{sys.executable} scripts/test_budget_old_cache_direction_backfill.py') != 0:
        print('BUDGET_OLD_CACHE_DIRECTION_BACKFILL_FAIL: test failed', file=sys.stderr)
        return 1
    print('BUDGET_OLD_CACHE_DIRECTION_BACKFILL_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
