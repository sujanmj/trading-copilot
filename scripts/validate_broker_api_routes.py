#!/usr/bin/env python3
"""Validate broker API routes (Stage 48L)."""

from __future__ import annotations

import os
import sys


def main() -> int:
    if os.system(f'{sys.executable} scripts/test_broker_api_routes.py') != 0:
        print('BROKER_API_ROUTES_FAIL: test failed', file=sys.stderr)
        return 1
    print('BROKER_API_ROUTES_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
