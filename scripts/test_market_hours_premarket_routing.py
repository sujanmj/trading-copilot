#!/usr/bin/env python3
"""Unit tests for market-hours /premarket routing (Stage 47E)."""

from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

IST = ZoneInfo('Asia/Kolkata')
MARKET_HOURS_NOW = datetime(2026, 6, 8, 10, 30, tzinfo=IST)


def _fail(msg: str) -> int:
    print(f'MARKET_HOURS_PREMARKET_ROUTING_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def _base_report(*, fresh_ok: bool = True) -> dict:
    return {
        'market_bias': 'Neutral',
        'top_setups': [
            {
                'ticker': 'RELIANCE',
                'setup': 'BULLISH scanner signal',
                'score': 82,
                'reasons': ['gap up', 'volume'],
                'source': 'scanner',
                'direction': 'BULLISH',
            },
            {
                'ticker': 'IDEA',
                'setup': 'Bearish / weak volume',
                'score': 45,
                'reasons': ['weak participation'],
                'source': 'intel',
                'direction': 'BEARISH',
            },
        ],
        'avoid': [],
        'market_mode': {'market_mode': 'INDIA_MARKET_HOURS'},
        'freshness_ok': fresh_ok,
        'freshness_header': '' if fresh_ok else '⚠️ DATA REFRESH INCOMPLETE — NO LIVE SETUPS',
        'hard_stale_lock': False,
        'riskoff_premarket': False,
        'sector_cues': {},
        'overnight_global': {},
        'weekend_research_mode': False,
    }


def main() -> int:
    from backend.analytics.premarket_conviction import (
        LIVE_MARKET_BRIEF_TITLE,
        LIVE_MARKET_WATCH_TITLE,
        format_premarket_telegram,
        _is_live_market_routing,
        _live_setup_status,
        _title_for_slot,
    )
    from backend.orchestration.alert_freshness_gate import PREMARKET_INCOMPLETE_HEADER

    mode = {'market_mode': 'INDIA_MARKET_HOURS'}
    if not _is_live_market_routing(mode, MARKET_HOURS_NOW):
        return _fail('10:30 INDIA_MARKET_HOURS should use live market routing')

    title_top = _title_for_slot('premarket_top3', MARKET_HOURS_NOW, full=False, mode_info=mode)
    if LIVE_MARKET_WATCH_TITLE not in title_top:
        return _fail(f'expected LIVE MARKET WATCH title, got {title_top!r}')
    if 'PREMARKET TOP SETUPS' in title_top:
        return _fail('market hours must not use PREMARKET TOP SETUPS title')

    title_full = _title_for_slot('premarket_action', MARKET_HOURS_NOW, full=True, mode_info=mode)
    if LIVE_MARKET_BRIEF_TITLE not in title_full:
        return _fail(f'expected LIVE MARKET BRIEF title, got {title_full!r}')

    fresh_text = format_premarket_telegram(
        full=False,
        report=_base_report(fresh_ok=True),
        slot='premarket_top3',
    )
    for needle in (LIVE_MARKET_WATCH_TITLE, 'Live watch:', 'Confirmed', 'Wait for volume', 'no blind entry'):
        if needle not in fresh_text:
            return _fail(f'fresh market-hours text missing {needle!r}')

    stale_text = format_premarket_telegram(
        full=False,
        report=_base_report(fresh_ok=False),
        slot='premarket_top3',
    )
    if PREMARKET_INCOMPLETE_HEADER not in stale_text:
        return _fail('stale market-hours must show DATA REFRESH INCOMPLETE header')

    full_text = format_premarket_telegram(
        full=True,
        report=_base_report(fresh_ok=True),
        slot='premarket_action',
    )
    if LIVE_MARKET_BRIEF_TITLE not in full_text:
        return _fail('/premarket full must use LIVE MARKET BRIEF title')

    if _live_setup_status({'setup': 'bearish weak', 'score': 40}) != 'Rejected':
        return _fail('bearish setup should be Rejected')
    if _live_setup_status({'setup': 'BULLISH', 'score': 80, 'source': 'scanner'}) != 'Confirmed':
        return _fail('strong scanner should be Confirmed')
    if _live_setup_status({'setup': 'WATCH', 'score': 55, 'source': 'intel'}) != 'Wait for volume':
        return _fail('weak intel should be Wait for volume')

    print('MARKET_HOURS_PREMARKET_ROUTING_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
