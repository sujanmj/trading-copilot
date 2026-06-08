#!/usr/bin/env python3
"""Unit tests for premarket hard stale lock (Stage 47D)."""

from __future__ import annotations

import os
import sys
from datetime import datetime, time
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

IST = ZoneInfo('Asia/Kolkata')
PREMARKET_NOW = datetime(2026, 6, 8, 8, 30, tzinfo=IST)


def _fail(msg: str) -> int:
    print(f'PREMARKET_HARD_STALE_LOCK_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.orchestration.alert_freshness_gate import (
        PREMARKET_HARD_STALE_SCORE_CAP,
        PREMARKET_INCOMPLETE_HEADER,
        PREMARKET_OLD_SESSION_NOTE,
        PREMARKET_WAIT_SCANNER_NOTE,
        PREMARKET_WATCHLIST_ONLY_NOTE,
        apply_hard_stale_lock_to_setups,
        is_premarket_hard_stale_window,
        premarket_hard_stale_lock,
    )
    from backend.analytics.premarket_conviction import format_premarket_telegram

    with patch('backend.analytics.market_calendar_router.is_india_market_day', return_value=True):
        if not is_premarket_hard_stale_window(PREMARKET_NOW):
            return _fail('08:30 trading day should be hard stale window')
        if is_premarket_hard_stale_window(datetime(2026, 6, 8, 9, 20, tzinfo=IST)):
            return _fail('09:20 should be outside hard stale window')

    with patch('backend.orchestration.alert_freshness_gate.is_premarket_hard_stale_window', return_value=True):
        with patch('backend.orchestration.alert_freshness_gate._collect_premarket_stale_keys', return_value=['scanner', 'market']):
            locked, header, keys, riskoff = premarket_hard_stale_lock(now=PREMARKET_NOW)
    if not locked:
        return _fail('stale feeds should trigger hard stale lock')
    if PREMARKET_INCOMPLETE_HEADER not in header:
        return _fail('missing NO LIVE SETUPS header')
    if 'scanner' not in keys:
        return _fail('expected stale scanner key')

    setups = [
        {
            'ticker': 'ABC',
            'setup': 'BULLISH scanner signal',
            'score': 85,
            'reasons': ['gap up'],
            'is_current_trading_session': True,
        },
        {
            'ticker': 'XYZ',
            'setup': 'WATCH',
            'score': 72,
            'reasons': ['intel'],
            'is_current_trading_session': False,
            'previous_session_research': True,
        },
    ]
    live, prev = apply_hard_stale_lock_to_setups(setups, locked=True, riskoff=False)
    for row in live + prev:
        if int(row.get('score', 0)) > PREMARKET_HARD_STALE_SCORE_CAP:
            return _fail('hard stale lock must cap score <= 50')
    if not any('Previous-session' in str(r.get('setup', '')) for r in prev + live):
        return _fail('bullish scanner should become previous-session research')

    report = {
        'market_bias': 'Bullish',
        'top_setups': live,
        'previous_session_movers': prev,
        'avoid': [],
        'market_mode': {'market_mode': 'INDIA_PREMARKET_MODE'},
        'freshness_ok': False,
        'freshness_header': PREMARKET_INCOMPLETE_HEADER,
        'hard_stale_lock': True,
        'riskoff_premarket': False,
        'sector_cues': {},
        'overnight_global': {},
    }
    text = format_premarket_telegram(full=False, report=report, slot='premarket_top3')
    for needle in (
        PREMARKET_INCOMPLETE_HEADER,
        PREMARKET_WATCHLIST_ONLY_NOTE,
        PREMARKET_OLD_SESSION_NOTE,
        PREMARKET_WAIT_SCANNER_NOTE,
        'Previous-session movers (research only)',
        'Top watch',
    ):
        if needle == 'Top watch' and needle in text:
            return _fail('hard stale lock must not show Top watch')
        if needle != 'Top watch' and needle not in text:
            return _fail(f'missing required text: {needle}')

    print('PREMARKET_HARD_STALE_LOCK_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
