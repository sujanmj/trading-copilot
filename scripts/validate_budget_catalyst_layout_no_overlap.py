#!/usr/bin/env python3
"""Validate budget catalyst vertical layout without overlap (Stage 48I)."""

from __future__ import annotations

import os
import sys


def main() -> int:
    if os.system(f'{sys.executable} scripts/test_budget_catalyst_layout_no_overlap.py') != 0:
        print('BUDGET_CATALYST_LAYOUT_NO_OVERLAP_FAIL: test failed', file=sys.stderr)
        return 1
    print('BUDGET_CATALYST_LAYOUT_NO_OVERLAP_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
