#!/usr/bin/env python3
"""Validate unified market freshness consistency (Stage 48R)."""

from __future__ import annotations

import os
import sys


def main() -> int:
    if os.system(f'{sys.executable} scripts/test_aihub_market_freshness_consistency.py') != 0:
        return 1
    print('AIHUB_MARKET_FRESHNESS_CONSISTENCY_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
