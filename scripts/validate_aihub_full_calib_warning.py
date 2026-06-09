#!/usr/bin/env python3
"""Validate /aihub full Calib warning when outcomes unresolved (Stage 48S)."""

from __future__ import annotations

import os
import sys


def main() -> int:
    if os.system(f'{sys.executable} scripts/test_aihub_full_calib_warning.py') != 0:
        return 1
    print('AIHUB_FULL_CALIB_WARNING_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
