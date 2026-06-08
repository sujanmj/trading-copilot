#!/usr/bin/env python3
"""Validate AIHub refresh route compat (Stage 48D)."""

from __future__ import annotations

import os
import sys


def main() -> int:
    if os.system(f'{sys.executable} scripts/test_aihub_refresh_route_compat.py') != 0:
        print('AIHUB_REFRESH_ROUTE_COMPAT_FAIL: test failed', file=sys.stderr)
        return 1
    print('AIHUB_REFRESH_ROUTE_COMPAT_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
