#!/usr/bin/env python3
"""Validate budget lite cache endpoints (Stage 48D)."""

from __future__ import annotations

import os
import sys


def main() -> int:
    if os.system(f'{sys.executable} scripts/test_budget_lite_cache_endpoint.py') != 0:
        print('BUDGET_LITE_CACHE_ENDPOINT_FAIL: test failed', file=sys.stderr)
        return 1
    print('BUDGET_LITE_CACHE_ENDPOINT_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
