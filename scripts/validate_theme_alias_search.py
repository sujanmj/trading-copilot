#!/usr/bin/env python3
"""Validate Theme Wishlist aliases, search, and category commands (Stage 47C)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)


def _fail(msg: str) -> int:
    print(f'THEME_ALIAS_SEARCH_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    if os.system(f'{sys.executable} scripts/test_theme_alias_search.py') != 0:
        return _fail('test_theme_alias_search.py failed')
    print('THEME_ALIAS_SEARCH_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
