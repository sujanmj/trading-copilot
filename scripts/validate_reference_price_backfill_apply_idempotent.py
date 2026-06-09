#!/usr/bin/env python3
"""Validate reference price backfill apply idempotency (Stage 49C)."""

from __future__ import annotations

import os
import sys


def main() -> int:
    if os.system(f'{sys.executable} scripts/test_reference_price_backfill_apply_idempotent.py') != 0:
        return 1
    if os.system(f'{sys.executable} scripts/validate_full_does_not_run_outcome_resolver.py') != 0:
        return 1
    print('REFERENCE_PRICE_BACKFILL_APPLY_IDEMPOTENT_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
