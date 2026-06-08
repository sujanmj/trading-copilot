#!/usr/bin/env python3
"""Validate Telegram freshness consistency (Stage 48K)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    shared = PROJECT_ROOT / 'backend/telegram/freshness_consistency.py'
    if not shared.is_file():
        print('TELEGRAM_FRESHNESS_CONSISTENCY_FAIL: missing freshness_consistency.py', file=sys.stderr)
        return 1
    src = shared.read_text(encoding='utf-8')
    if 'BUDGET_CACHE_FRESH_THRESHOLD_MINUTES = 90' not in src:
        print('TELEGRAM_FRESHNESS_CONSISTENCY_FAIL: missing 90m threshold', file=sys.stderr)
        return 1
    if os.system(f'{sys.executable} scripts/test_telegram_freshness_consistency.py') != 0:
        print('TELEGRAM_FRESHNESS_CONSISTENCY_FAIL: test failed', file=sys.stderr)
        return 1
    print('TELEGRAM_FRESHNESS_CONSISTENCY_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
