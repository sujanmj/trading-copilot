#!/usr/bin/env python3
"""Validate Telegram /status theme cache labels (Stage 48H)."""

from __future__ import annotations

import os
import sys


def main() -> int:
    if os.system(f'{sys.executable} scripts/test_telegram_status_theme_cache_labels.py') != 0:
        print('TELEGRAM_STATUS_THEME_CACHE_LABELS_FAIL: test failed', file=sys.stderr)
        return 1
    print('TELEGRAM_STATUS_THEME_CACHE_LABELS_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
