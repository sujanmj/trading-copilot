#!/usr/bin/env python3
"""Validate budget stock table layout (Stage 48I)."""

from __future__ import annotations

import os
import sys


def main() -> int:
    if os.system(f'{sys.executable} scripts/test_budget_stock_table_layout.py') != 0:
        print('BUDGET_STOCK_TABLE_LAYOUT_FAIL: test failed', file=sys.stderr)
        return 1
    print('BUDGET_STOCK_TABLE_LAYOUT_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
