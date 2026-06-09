#!/usr/bin/env python3
"""Validate /status vs /aihub scan freshness consistency (Stage 48Q)."""

from __future__ import annotations

import os
import sys


def main() -> int:
    if os.system(f'{sys.executable} scripts/test_freshness_consistency_status_aihub.py') != 0:
        return 1
    print('FRESHNESS_CONSISTENCY_STATUS_AIHUB_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
