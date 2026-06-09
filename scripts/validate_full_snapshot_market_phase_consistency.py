#!/usr/bin/env python3
"""Validate /full snapshot market phase consistency (Stage 48S)."""

from __future__ import annotations

import os
import sys


def main() -> int:
    if os.system(f'{sys.executable} scripts/test_full_snapshot_market_phase_consistency.py') != 0:
        return 1
    print('FULL_SNAPSHOT_MARKET_PHASE_CONSISTENCY_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
