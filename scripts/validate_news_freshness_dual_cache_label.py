#!/usr/bin/env python3
"""Validate dual news cache freshness labels (Stage 48R)."""

from __future__ import annotations

import os
import sys


def main() -> int:
    if os.system(f'{sys.executable} scripts/test_news_freshness_dual_cache_label.py') != 0:
        return 1
    print('NEWS_FRESHNESS_DUAL_CACHE_LABEL_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
