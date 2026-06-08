#!/usr/bin/env python3
"""Validate action plan India mode lock (Stage 48K)."""

from __future__ import annotations

import os
import sys


def main() -> int:
    if os.system(f'{sys.executable} scripts/test_action_plan_no_usa_mode.py') != 0:
        print('ACTION_PLAN_NO_USA_MODE_FAIL: test failed', file=sys.stderr)
        return 1
    print('ACTION_PLAN_NO_USA_MODE_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
