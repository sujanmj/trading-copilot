#!/usr/bin/env python3
"""Validate broker evidence freshness + headline truncation (Stage 48Q)."""

from __future__ import annotations

import os
import sys


def main() -> int:
    if os.system(f'{sys.executable} scripts/test_broker_freshness_and_truncation_cleanup.py') != 0:
        return 1
    print('BROKER_FRESHNESS_AND_TRUNCATION_CLEANUP_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
