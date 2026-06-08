#!/usr/bin/env python3
"""Validate /status and /budget share freshness threshold (Stage 48K)."""

from __future__ import annotations

import os
import sys


def main() -> int:
    if os.system(f'{sys.executable} scripts/test_budget_status_same_freshness_threshold.py') != 0:
        print('BUDGET_STATUS_SAME_FRESHNESS_THRESHOLD_FAIL: test failed', file=sys.stderr)
        return 1
    print('BUDGET_STATUS_SAME_FRESHNESS_THRESHOLD_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
