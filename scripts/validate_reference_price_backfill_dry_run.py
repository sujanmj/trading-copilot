#!/usr/bin/env python3
"""Validate reference price backfill dry-run (Stage 49C)."""

from __future__ import annotations

import os
import sys


def main() -> int:
    if os.system(f'{sys.executable} scripts/test_reference_price_backfill_dry_run.py') != 0:
        return 1
    print('REFERENCE_PRICE_BACKFILL_DRY_RUN_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
