#!/usr/bin/env python3
"""Validate broker live cache persistence (Stage 48M)."""

from __future__ import annotations

import os
import sys


def main() -> int:
    if os.system(f'{sys.executable} scripts/test_broker_live_cache_persistence.py') != 0:
        return 1
    print('BROKER_LIVE_CACHE_PERSISTENCE_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
