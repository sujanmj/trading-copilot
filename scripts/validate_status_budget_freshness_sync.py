#!/usr/bin/env python3
"""Validate /status budget freshness sync (Stage 48H)."""

from __future__ import annotations

import os
import sys


def main() -> int:
    if os.system(f'{sys.executable} scripts/test_status_budget_freshness_sync.py') != 0:
        print('STATUS_BUDGET_FRESHNESS_SYNC_FAIL: test failed', file=sys.stderr)
        return 1
    print('STATUS_BUDGET_FRESHNESS_SYNC_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
