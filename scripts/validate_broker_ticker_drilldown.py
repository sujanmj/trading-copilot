#!/usr/bin/env python3
"""Validate broker ticker drilldown (Stage 48L)."""

from __future__ import annotations

import os
import sys


def main() -> int:
    if os.system(f'{sys.executable} scripts/test_broker_ticker_drilldown.py') != 0:
        print('BROKER_TICKER_DRILLDOWN_FAIL: test failed', file=sys.stderr)
        return 1
    print('BROKER_TICKER_DRILLDOWN_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
