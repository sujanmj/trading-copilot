#!/usr/bin/env python3
"""Validate live broker today/tomorrow integration (Stage 48M)."""

from __future__ import annotations

import os
import sys


def main() -> int:
    if os.system(f'{sys.executable} scripts/test_broker_today_tomorrow_live_integration.py') != 0:
        return 1
    if os.system(f'{sys.executable} scripts/validate_broker_today_tomorrow_integration.py') != 0:
        return 1
    print('BROKER_TODAY_TOMORROW_LIVE_INTEGRATION_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
