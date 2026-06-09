#!/usr/bin/env python3
"""Validate no fake broker support from watchlist (Stage 48O)."""

from __future__ import annotations

import os
import sys


def main() -> int:
    if os.system(f'{sys.executable} scripts/test_broker_today_no_fake_support.py') != 0:
        return 1
    print('BROKER_TODAY_NO_FAKE_SUPPORT_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
