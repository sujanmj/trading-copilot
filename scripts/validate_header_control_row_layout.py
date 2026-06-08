#!/usr/bin/env python3
"""Validate single-row header layout (Stage 48C)."""

from __future__ import annotations

import os
import sys


def _fail(msg: str) -> int:
    print(f'HEADER_CONTROL_ROW_LAYOUT_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    if os.system(f'{sys.executable} scripts/test_header_control_row_layout.py') != 0:
        return _fail('test_header_control_row_layout.py failed')
    print('HEADER_CONTROL_ROW_LAYOUT_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
