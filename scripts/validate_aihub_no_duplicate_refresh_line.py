#!/usr/bin/env python3
"""Validate AI Hub refresh hint dedupe (Stage 48S)."""

from __future__ import annotations

import os
import sys


def main() -> int:
    if os.system(f'{sys.executable} scripts/test_aihub_no_duplicate_refresh_line.py') != 0:
        return 1
    print('AIHUB_NO_DUPLICATE_REFRESH_LINE_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
