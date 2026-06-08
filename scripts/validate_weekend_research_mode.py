#!/usr/bin/env python3
"""Validate weekend research mode pack (Stage 46J)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)


def _fail(msg: str) -> int:
    print(f'WEEKEND_RESEARCH_MODE_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    for rel in (
        'backend/analytics/premarket_conviction.py',
        'backend/analytics/market_calendar_router.py',
    ):
        if not (PROJECT_ROOT / rel).is_file():
            return _fail(f'missing {rel}')

    pc_src = (PROJECT_ROOT / 'backend/analytics/premarket_conviction.py').read_text(encoding='utf-8')
    for needle in (
        'WEEKEND RESEARCH WATCHLIST',
        'WEEKEND RESEARCH BRIEF',
        'Confirm on next trading session after 9:15',
        'Use /refresh full for fresh closed-market research.',
        'Cache is stale — run /refresh full for updated research.',
        "'stage': '47E'",
    ):
        if needle not in pc_src:
            return _fail(f'premarket_conviction missing {needle}')

    router_src = (PROJECT_ROOT / 'backend/analytics/market_calendar_router.py').read_text(encoding='utf-8')
    for needle in ('is_weekend_holiday_research_telegram_mode', 'is_manual_refresh_suggested_mode'):
        if needle not in router_src:
            return _fail(f'market_calendar_router missing {needle}')

    proc = os.system(f'{sys.executable} scripts/test_weekend_research_mode.py')
    if proc != 0:
        return _fail('test_weekend_research_mode.py failed')

    print('WEEKEND_RESEARCH_MODE_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
