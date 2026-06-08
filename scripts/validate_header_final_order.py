#!/usr/bin/env python3
"""Validate final header order (Stage 48D)."""

from __future__ import annotations

import os
import sys


def main() -> int:
    if os.system(f'{sys.executable} scripts/test_header_final_order.py') != 0:
        print('HEADER_FINAL_ORDER_FAIL: test failed', file=sys.stderr)
        return 1
    print('HEADER_FINAL_ORDER_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
