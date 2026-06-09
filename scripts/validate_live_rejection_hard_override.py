#!/usr/bin/env python3
"""Validate hard live rejection override (Stage 48R)."""

from __future__ import annotations

import os
import sys


def main() -> int:
    if os.system(f'{sys.executable} scripts/test_live_rejection_hard_override.py') != 0:
        return 1
    print('LIVE_REJECTION_HARD_OVERRIDE_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
