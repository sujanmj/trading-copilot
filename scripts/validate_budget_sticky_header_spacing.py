#!/usr/bin/env python3
"""Validate budget sticky header spacing (Stage 48I)."""

from __future__ import annotations

import os
import sys


def main() -> int:
    if os.system(f'{sys.executable} scripts/test_budget_sticky_header_spacing.py') != 0:
        print('BUDGET_STICKY_HEADER_SPACING_FAIL: test failed', file=sys.stderr)
        return 1
    print('BUDGET_STICKY_HEADER_SPACING_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
