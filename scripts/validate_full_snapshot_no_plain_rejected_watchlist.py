#!/usr/bin/env python3
"""Validate /full plain rejected watchlist guard (Stage 48U)."""

from __future__ import annotations

import os
import sys


def main() -> int:
    if os.system(f'{sys.executable} scripts/test_full_snapshot_no_plain_rejected_watchlist.py') != 0:
        return 1
    print('FULL_SNAPSHOT_NO_PLAIN_REJECTED_WATCHLIST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
