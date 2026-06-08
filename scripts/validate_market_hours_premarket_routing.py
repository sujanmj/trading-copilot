#!/usr/bin/env python3
"""Validate market-hours /premarket routing (Stage 47E)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)


def _fail(msg: str) -> int:
    print(f'MARKET_HOURS_PREMARKET_ROUTING_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    src = (PROJECT_ROOT / 'backend/analytics/premarket_conviction.py').read_text(encoding='utf-8')
    for needle in (
        "LIVE_MARKET_WATCH_TITLE = '🔎 LIVE MARKET WATCH'",
        "LIVE_MARKET_BRIEF_TITLE = '📊 LIVE MARKET BRIEF'",
        '_is_live_market_routing',
        '_live_setup_status',
        'INDIA_MARKET_HOURS',
        "'stage': '47F'",
    ):
        if needle not in src:
            return _fail(f'premarket_conviction.py missing {needle!r}')

    if os.system(f'{sys.executable} scripts/test_market_hours_premarket_routing.py') != 0:
        return _fail('test_market_hours_premarket_routing.py failed')
    print('MARKET_HOURS_PREMARKET_ROUTING_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
