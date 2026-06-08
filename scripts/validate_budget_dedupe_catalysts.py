#!/usr/bin/env python3
"""Validate budget catalyst dedupe (Stage 48F)."""

from __future__ import annotations

import os
import sys


def main() -> int:
    if os.system(f'{sys.executable} scripts/test_budget_dedupe_catalysts.py') != 0:
        print('BUDGET_DEDUPE_CATALYSTS_FAIL: test failed', file=sys.stderr)
        return 1
    print('BUDGET_DEDUPE_CATALYSTS_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
