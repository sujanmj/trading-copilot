#!/usr/bin/env python3
"""Validate budget frontend dark catalyst cards (Stage 48I)."""

from __future__ import annotations

import os
import sys


def main() -> int:
    if os.system(f'{sys.executable} scripts/test_budget_frontend_dark_cards.py') != 0:
        print('BUDGET_FRONTEND_DARK_CARDS_FAIL: test failed', file=sys.stderr)
        return 1
    print('BUDGET_FRONTEND_DARK_CARDS_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
