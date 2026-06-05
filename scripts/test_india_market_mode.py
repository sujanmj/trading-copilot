#!/usr/bin/env python3
"""Unit tests for India Telegram market mode display (Stage 46I)."""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)


def _fail(msg: str) -> int:
    print(f'INDIA_MARKET_MODE_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def _ist_to_utc(hour: int, minute: int, day: str = '2026-06-05') -> datetime:
    from zoneinfo import ZoneInfo
    ist = ZoneInfo('Asia/Kolkata')
    local = datetime.fromisoformat(f'{day}T{hour:02d}:{minute:02d}:00').replace(tzinfo=ist)
    return local.astimezone(timezone.utc)


def main() -> int:
    from backend.analytics.market_calendar_router import get_india_telegram_mode
    from backend.analytics.premarket_conviction import format_premarket_telegram

    cases = [
        (_ist_to_utc(8, 0), 'INDIA_PREMARKET_MODE'),
        (_ist_to_utc(9, 5), 'INDIA_PREOPEN_MODE'),
        (_ist_to_utc(10, 0), 'INDIA_MARKET_HOURS'),
        (_ist_to_utc(16, 0), 'INDIA_POSTMARKET_MODE'),
        (_ist_to_utc(18, 0), 'INDIA_AFTER_HOURS'),
    ]
    for now_utc, expected in cases:
        mode = get_india_telegram_mode(now_utc)
        label = mode.get('market_mode', '')
        if expected not in label:
            return _fail(f'at {now_utc} expected {expected}, got {label}')
        if 'USA_POSTMARKET' in label:
            return _fail(f'India morning must not show USA_POSTMARKET: {label}')

    report = {
        'market_bias': 'Neutral',
        'top_setups': [],
        'avoid': [],
        'market_mode': {'market_mode': 'INDIA_PREMARKET_MODE'},
        'freshness_ok': True,
        'sector_cues': {},
        'overnight_global': {'sentiment_formatted': 'US: Neutral (+0.00%)'},
    }
    text = format_premarket_telegram(full=True, report=report, slot='premarket_action')
    if 'USA_POSTMARKET_MODE' in text:
        return _fail('premarket telegram leaked USA_POSTMARKET_MODE')
    if 'US/global context only' not in text:
        return _fail('missing US/global context only label')

    print('INDIA_MARKET_MODE_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
