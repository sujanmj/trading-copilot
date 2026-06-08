#!/usr/bin/env python3
"""Validate exact header order (Stage 48E)."""

from __future__ import annotations

import os
import sys


def main() -> int:
    if os.system(f'{sys.executable} scripts/test_header_exact_order.py') != 0:
        print('HEADER_EXACT_ORDER_FAIL: test failed', file=sys.stderr)
        return 1
    print('HEADER_EXACT_ORDER_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
