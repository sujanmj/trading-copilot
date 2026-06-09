#!/usr/bin/env python3
"""Validate /today after-hours wording (Stage 48S)."""

from __future__ import annotations

import os
import sys


def main() -> int:
    if os.system(f'{sys.executable} scripts/test_after_hours_today_wording.py') != 0:
        return 1
    print('AFTER_HOURS_TODAY_WORDING_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
