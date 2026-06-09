#!/usr/bin/env python3
"""Validate generic watchlist filter (Stage 48O)."""

from __future__ import annotations

import os
import sys


def main() -> int:
    if os.system(f'{sys.executable} scripts/test_broker_generic_watchlist_filter.py') != 0:
        return 1
    print('BROKER_GENERIC_WATCHLIST_FILTER_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
