#!/usr/bin/env python3
"""Validate AI Hub cache-first tabs (Stage 48C)."""

from __future__ import annotations

import os
import sys


def _fail(msg: str) -> int:
    print(f'AIHUB_CACHE_FIRST_TABS_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    if os.system(f'{sys.executable} scripts/test_aihub_cache_first_tabs.py') != 0:
        return _fail('test_aihub_cache_first_tabs.py failed')
    print('AIHUB_CACHE_FIRST_TABS_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
