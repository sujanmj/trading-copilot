#!/usr/bin/env python3
"""Validate AIHub rejected watchlist clarity (Stage 48T)."""

from __future__ import annotations

import os
import sys


def main() -> int:
    if os.system(f'{sys.executable} scripts/test_aihub_rejected_watchlist_clarity.py') != 0:
        return 1
    print('AIHUB_REJECTED_WATCHLIST_CLARITY_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
