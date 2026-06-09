#!/usr/bin/env python3
"""Unit tests — compact stale report labels use stale · Xh (Stage 48Q)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

os.environ.setdefault('DISABLE_TELEGRAM', '1')
os.environ.setdefault('DISABLE_TELEGRAM_SENDS', '1')


def _fail(msg: str) -> int:
    print(f'REPORT_STALE_LABEL_CONSISTENCY_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.telegram.freshness_consistency import format_compact_freshness_line

    line_11h = format_compact_freshness_line('Report', 660)
    if 'Report: stale · 11h' != line_11h:
        return _fail(f'expected Report: stale · 11h got {line_11h!r}')

    line_100m = format_compact_freshness_line('Report', 100)
    if 'stale · 1h' not in line_100m:
        return _fail(f'100m stale report must use stale · 1h got {line_100m!r}')

    fresh_line = format_compact_freshness_line('Scanner', 2)
    if fresh_line != 'Scanner: fresh · 2m':
        return _fail(f'unexpected fresh scanner line {fresh_line!r}')

    news_line = format_compact_freshness_line('News', 3)
    if news_line != 'News: fresh · 3m':
        return _fail(f'unexpected fresh news line {news_line!r}')

    print('REPORT_STALE_LABEL_CONSISTENCY_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
