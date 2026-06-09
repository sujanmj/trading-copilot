#!/usr/bin/env python3
"""Validate broker refresh lists tickers (Stage 48N)."""

from __future__ import annotations

import os
import sys


def main() -> int:
    if os.system(f'{sys.executable} scripts/test_broker_refresh_lists_tickers.py') != 0:
        return 1
    print('BROKER_REFRESH_LISTS_TICKERS_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
