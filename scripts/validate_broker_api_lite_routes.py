#!/usr/bin/env python3
"""Validate broker lite API routes (Stage 48E)."""

from __future__ import annotations

import os
import sys


def main() -> int:
    if os.system(f'{sys.executable} scripts/test_broker_api_lite_routes.py') != 0:
        print('BROKER_API_LITE_ROUTES_FAIL: test failed', file=sys.stderr)
        return 1
    print('BROKER_API_LITE_ROUTES_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
