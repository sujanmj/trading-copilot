#!/usr/bin/env python3
"""Unit tests — refresh hint appears once in AI Hub brain paths (Stage 48S)."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

REFRESH = 'Use /refresh full for fresh closed-market research.'


def _fail(msg: str) -> int:
    print(f'AIHUB_NO_DUPLICATE_REFRESH_LINE_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.analytics.premarket_conviction import MANUAL_REFRESH_SUGGESTION
    from backend.telegram.response_format import format_aihub_payload

    if MANUAL_REFRESH_SUGGESTION != REFRESH:
        return _fail('refresh suggestion constant mismatch')

    payload = {
        'source': 'cache',
        'cache_age_seconds': 7200,
        'summary': {'stale': True},
        'items': [{'title': 'cached brain note'}],
        'warnings': [],
    }

    with patch('backend.analytics.market_calendar_router.is_manual_refresh_suggested_mode', return_value=True):
        text = format_aihub_payload('brain', payload)

    count = text.count(REFRESH)
    if count != 1:
        return _fail(f'expected refresh line once in /aihub brain got {count} occurrences')

    print('AIHUB_NO_DUPLICATE_REFRESH_LINE_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
