#!/usr/bin/env python3
"""Validate header AI nav first-row layout (Stage 48B)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _fail(msg: str) -> int:
    print(f'HEADER_AI_NAV_LAYOUT_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    if os.system(f'{sys.executable} scripts/test_header_ai_nav_layout.py') != 0:
        return _fail('test_header_ai_nav_layout.py failed')
    print('HEADER_AI_NAV_LAYOUT_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
