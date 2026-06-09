#!/usr/bin/env python3
"""Validate tomorrow live rejection warning (Stage 48R)."""

from __future__ import annotations

import os
import sys


def main() -> int:
    if os.system(f'{sys.executable} scripts/test_tomorrow_live_rejection_warning.py') != 0:
        return 1
    print('TOMORROW_LIVE_REJECTION_WARNING_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
