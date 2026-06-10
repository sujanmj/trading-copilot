#!/usr/bin/env python3
"""Validate My Feed cannot create BUY/SELL alone (Stage 50A)."""

from __future__ import annotations

import os
import sys


def main() -> int:
    if os.system(f'{sys.executable} scripts/test_my_feed_cannot_create_buy_sell_alone.py') != 0:
        return 1
    print('MY_FEED_CANNOT_CREATE_BUY_SELL_ALONE_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
