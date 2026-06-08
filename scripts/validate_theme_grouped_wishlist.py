#!/usr/bin/env python3
"""Validate grouped Theme Wishlist list output (Stage 47C)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)


def _fail(msg: str) -> int:
    print(f'THEME_GROUPED_WISHLIST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    if os.system(f'{sys.executable} scripts/test_theme_grouped_wishlist.py') != 0:
        return _fail('test_theme_grouped_wishlist.py failed')
    print('THEME_GROUPED_WISHLIST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
