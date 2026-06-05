#!/usr/bin/env python3
"""Unit tests for weekend/holiday research premarket mode (Stage 46J)."""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)


def _fail(msg: str) -> int:
    print(f'WEEKEND_RESEARCH_MODE_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def _weekend_report(**overrides) -> dict:
    base = {
        'generated_at': '2026-06-06T10:00:00+05:30',
        'cache_age_hours': 14.5,
        'cache_stale_12h': True,
        'cache_stale_24h': False,
        'cache_stale_message': 'Cache is stale — run /refresh full for updated research.',
        'market_bias': 'Neutral',
        'top_setups': [
            {
                'ticker': 'INFY',
                'setup': 'WATCH',
                'score': 55,
                'source': 'final_confidence',
                'research_label': 'Research only',
                'reasons': ['Friday confidence context'],
            },
            {
                'ticker': 'RELIANCE',
                'setup': 'WATCH',
                'score': 62,
                'source': 'watchlist',
                'research_label': 'stale watchlist',
                'reasons': ['Friday close context'],
            },
            {
                'ticker': 'TCS',
                'setup': 'scanner signal',
                'score': 60,
                'source': 'scanner',
                'research_label': 'next-session watch',
                'reasons': ['Overnight move'],
            },
        ],
        'avoid': [{'ticker': 'XYZ', 'reason': 'weak participation'}],
        'sector_cues': {'bullish': ['IT'], 'bearish': ['Auto']},
        'weekend_research_mode': True,
        'market_mode': {'market_mode': 'Weekend — Research', 'mode_code': 'RESEARCH_MODE'},
        'freshness_ok': True,
        'overnight_global': {},
    }
    base.update(overrides)
    return base


def main() -> int:
    from backend.analytics.market_calendar_router import (
        get_india_telegram_mode,
        is_manual_refresh_suggested_mode,
        is_weekend_holiday_research_telegram_mode,
    )
    from backend.analytics.premarket_conviction import (
        CACHE_STALE_12H_MSG,
        MANUAL_REFRESH_SUGGESTION,
        NEXT_SESSION_CONFIRM,
        WEEKEND_RESEARCH_FULL_TITLE,
        WEEKEND_RESEARCH_TOP_TITLE,
        WEEKEND_SCORE_CAP,
        _apply_weekend_research_caps,
        _cache_stale_state,
        format_premarket_telegram,
    )

    weekend_utc = datetime(2026, 6, 6, 6, 0, tzinfo=timezone.utc)
    mode = get_india_telegram_mode(weekend_utc)
    if not is_weekend_holiday_research_telegram_mode(mode):
        return _fail('Saturday should be weekend research mode')
    if 'Weekend' not in str(mode.get('market_mode', '')):
        return _fail('weekend label missing from india telegram mode')

    capped = _apply_weekend_research_caps([{'ticker': 'A', 'score': 90, 'setup': 'STRONG', 'source': 'scanner'}])
    if capped[0]['score'] > WEEKEND_SCORE_CAP:
        return _fail('weekend score cap should be <=65')
    if capped[0].get('research_label') != 'next-session watch':
        return _fail('scanner should map to next-session watch label')

    from zoneinfo import ZoneInfo

    ist = ZoneInfo('Asia/Kolkata')
    stale_12, stale_24, msg = _cache_stale_state(
        '2026-06-05T08:00:00+05:30',
        now=datetime(2026, 6, 6, 10, 0, tzinfo=ist),
    )
    if not stale_12 or not stale_24:
        return _fail('26h report should be stale at 12h and 24h')
    if CACHE_STALE_12H_MSG not in msg:
        return _fail('missing stale cache message')

    top = format_premarket_telegram(full=False, report=_weekend_report())
    if WEEKEND_RESEARCH_TOP_TITLE not in top:
        return _fail('top view missing weekend research title')
    if top.count('PREMARKET TOP SETUPS') > 1 or (
        'PREMARKET TOP SETUPS' in top and 'NOT PREMARKET TOP SETUPS' not in top
    ):
        return _fail('weekend top view must not use live premarket top setups title')
    for phrase in (
        'No live premarket signal',
        'Next trading session confirmation required',
        'Fresh scan required before market open',
        NEXT_SESSION_CONFIRM,
        'Research only',
        'stale watchlist',
        'next-session watch',
    ):
        if phrase not in top:
            return _fail(f'missing weekend phrase: {phrase}')
    if 'confirm after 9:15' in top.lower() and NEXT_SESSION_CONFIRM.lower() not in top.lower():
        return _fail('weekend must use next-session confirm wording')
    if MANUAL_REFRESH_SUGGESTION not in top:
        return _fail('weekend top view missing manual refresh suggestion')

    full = format_premarket_telegram(full=True, report=_weekend_report())
    if WEEKEND_RESEARCH_FULL_TITLE not in full:
        return _fail('full view missing weekend research brief title')
    for marker in (
        'Last report:',
        'Cache age:',
        'Top research watchlist:',
        'Risk themes:',
        'Sectors to monitor next session:',
        'Required Monday refresh:',
    ):
        if marker not in full:
            return _fail(f'full weekend brief missing: {marker}')
    if 'buy now' in full.lower():
        return _fail('weekend full brief must avoid trade-like language')

    stale_report = _weekend_report(cache_age_hours=30, cache_stale_24h=True)
    stale_report['top_setups'] = _apply_weekend_research_caps(
        stale_report['top_setups'],
        stale_24h=True,
    )
    stale_text = format_premarket_telegram(full=False, report=stale_report)
    if CACHE_STALE_12H_MSG not in stale_text:
        return _fail('stale cache message missing from weekend output')

    after_hours_mode = {'market_mode': 'INDIA_AFTER_HOURS', 'mode_code': 'INDIA_AFTER_HOURS_MODE'}
    if not is_manual_refresh_suggested_mode(after_hours_mode):
        return _fail('after-hours should suggest manual refresh')

    weekday_mode = {'market_mode': 'INDIA_PREMARKET_MODE', 'mode_code': 'INDIA_PREMARKET_MODE'}
    if is_weekend_holiday_research_telegram_mode(weekday_mode):
        return _fail('premarket weekday should not be weekend research mode')

    with patch('backend.analytics.premarket_conviction._is_weekend_holiday_research', return_value=False):
        weekday_text = format_premarket_telegram(
            full=False,
            report={
                'market_bias': 'Neutral',
                'top_setups': [],
                'avoid': [],
                'market_mode': weekday_mode,
                'freshness_ok': True,
                'weekend_research_mode': False,
                'sector_cues': {},
                'overnight_global': {},
            },
            slot='premarket_top3',
        )
    if 'PREMARKET TOP SETUPS' not in weekday_text:
        return _fail('weekday premarket title should remain')

    print('WEEKEND_RESEARCH_MODE_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
