#!/usr/bin/env python3
"""Validate frontend boot avoids heavy refresh (Stage 48C)."""

from __future__ import annotations

import os
import sys


def _fail(msg: str) -> int:
    print(f'FRONTEND_BOOT_NO_HEAVY_REFRESH_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    if os.system(f'{sys.executable} scripts/test_frontend_boot_no_heavy_refresh.py') != 0:
        return _fail('test_frontend_boot_no_heavy_refresh.py failed')
    print('FRONTEND_BOOT_NO_HEAVY_REFRESH_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
