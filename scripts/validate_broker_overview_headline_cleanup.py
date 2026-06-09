#!/usr/bin/env python3
"""Validate broker overview headline truncation (Stage 48R)."""

from __future__ import annotations

import os
import sys


def main() -> int:
    if os.system(f'{sys.executable} scripts/test_broker_overview_headline_cleanup.py') != 0:
        return 1
    print('BROKER_OVERVIEW_HEADLINE_CLEANUP_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
