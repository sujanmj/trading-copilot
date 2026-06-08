#!/usr/bin/env python3
"""Validate broker today/tomorrow integration (Stage 48L)."""

from __future__ import annotations

import os
import sys


def main() -> int:
    if os.system(f'{sys.executable} scripts/test_broker_today_tomorrow_integration.py') != 0:
        print('BROKER_TODAY_TOMORROW_INTEGRATION_FAIL: test failed', file=sys.stderr)
        return 1
    print('BROKER_TODAY_TOMORROW_INTEGRATION_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
