#!/usr/bin/env python3
"""Validate budget catalyst drilldown (Stage 48G)."""

from __future__ import annotations

import os
import sys


def main() -> int:
    if os.system(f'{sys.executable} scripts/test_budget_catalyst_drilldown.py') != 0:
        print('BUDGET_CATALYST_DRILLDOWN_FAIL: test failed', file=sys.stderr)
        return 1
    print('BUDGET_CATALYST_DRILLDOWN_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
