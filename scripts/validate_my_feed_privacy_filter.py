#!/usr/bin/env python3
"""Validate My Feed privacy filter (Stage 50A)."""

from __future__ import annotations

import os
import sys


def main() -> int:
    if os.system(f'{sys.executable} scripts/test_my_feed_privacy_filter.py') != 0:
        return 1
    print('MY_FEED_PRIVACY_FILTER_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
