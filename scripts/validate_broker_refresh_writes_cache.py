#!/usr/bin/env python3
"""Validate broker refresh cache write (Stage 48M)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    src = (PROJECT_ROOT / 'backend/analytics/broker_intelligence.py').read_text(encoding='utf-8')
    for needle in ('verify_broker_cache_write', 'format_broker_refresh_telegram', 'cache_verify'):
        if needle not in src:
            print(f'BROKER_REFRESH_WRITES_CACHE_FAIL: missing {needle}', file=sys.stderr)
            return 1
    if os.system(f'{sys.executable} scripts/test_broker_refresh_writes_cache.py') != 0:
        return 1
    print('BROKER_REFRESH_WRITES_CACHE_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
