#!/usr/bin/env python3
"""Validate /aihub calib unresolved warnings (Stage 48R)."""

from __future__ import annotations

import os
import sys


def main() -> int:
    if os.system(f'{sys.executable} scripts/test_aihub_calib_unresolved_warning.py') != 0:
        return 1
    print('AIHUB_CALIB_UNRESOLVED_WARNING_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
