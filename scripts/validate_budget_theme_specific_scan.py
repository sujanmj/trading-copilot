#!/usr/bin/env python3
"""Validate theme-specific budget scan (Stage 48G)."""

from __future__ import annotations

import os
import sys


def main() -> int:
    if os.system(f'{sys.executable} scripts/test_budget_theme_specific_scan.py') != 0:
        print('BUDGET_THEME_SPECIFIC_SCAN_FAIL: test failed', file=sys.stderr)
        return 1
    print('BUDGET_THEME_SPECIFIC_SCAN_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
