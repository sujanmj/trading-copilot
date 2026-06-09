#!/usr/bin/env python3
"""Validate /aihub calib real sample rendering (Stage 49A)."""

from __future__ import annotations

import os
import sys


def main() -> int:
    if os.system(f'{sys.executable} scripts/test_aihub_calib_real_sample_render.py') != 0:
        return 1
    print('AIHUB_CALIB_REAL_SAMPLE_RENDER_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
