#!/usr/bin/env python3
"""Validate budget direction pills UI (Stage 48I)."""

from __future__ import annotations

import os
import sys


def main() -> int:
    if os.system(f'{sys.executable} scripts/test_budget_direction_pills_ui.py') != 0:
        print('BUDGET_DIRECTION_PILLS_UI_FAIL: test failed', file=sys.stderr)
        return 1
    print('BUDGET_DIRECTION_PILLS_UI_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
