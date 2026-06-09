#!/usr/bin/env python3
"""Validate AVANTIFEED not top when live bearish (Stage 48R)."""

from __future__ import annotations

import os
import sys


def main() -> int:
    if os.system(f'{sys.executable} scripts/test_avantifeed_not_top_when_live_bearish.py') != 0:
        return 1
    print('AVANTIFEED_NOT_TOP_WHEN_LIVE_BEARISH_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
