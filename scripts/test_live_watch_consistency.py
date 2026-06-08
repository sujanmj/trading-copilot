#!/usr/bin/env python3
"""Unit tests for live watch / premarket consistency (Stage 47F)."""

from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

IST = ZoneInfo('Asia/Kolkata')
MARKET_HOURS_NOW = datetime(2026, 6, 8, 10, 30, tzinfo=IST)


def _fail(msg: str) -> int:
    print(f'LIVE_WATCH_CONSISTENCY_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def _base_report(*, fresh_ok: bool = True, non_critical: list[str] | None = None) -> dict:
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
        ],
        'avoid': [],
        'market_mode': {'market_mode': 'INDIA_MARKET_HOURS'},
        'freshness_ok': fresh_ok,
        'freshness_header': '' if fresh_ok else '⚠️ DATA REFRESH INCOMPLETE — NO LIVE SETUPS',
        'non_critical_stale_keys': non_critical or [],
        'hard_stale_lock': False,
        'riskoff_premarket': False,
        'sector_cues': {},
        'overnight_global': {},
        'weekend_research_mode': False,
    }


def main() -> int:
    from backend.analytics.premarket_conviction import (
        LIVE_MARKET_WATCH_TITLE,
        OPEN_CONFIRMED_ACTION,
        format_premarket_telegram,
    )
    from backend.orchestration.alert_freshness_gate import (
        CRITICAL_MARKET_HOURS_KEYS,
        _split_critical_stale_keys,
        premarket_freshness_state,
    )

    critical, non_critical = _split_critical_stale_keys(['scanner', 'intel'], now=MARKET_HOURS_NOW)
    if 'scanner' not in critical:
        return _fail('scanner should be critical during INDIA_MARKET_HOURS')
    if 'intel' not in non_critical:
        return _fail('intel should be non-critical during INDIA_MARKET_HOURS')

    ok, header, crit, non_crit = premarket_freshness_state(now=MARKET_HOURS_NOW)
    if not isinstance(ok, bool):
        return _fail('premarket_freshness_state must return ok flag')

    stale_text = format_premarket_telegram(
        full=False,
        report=_base_report(fresh_ok=False),
        slot='premarket_top3',
    )
    if 'Top watch' in stale_text:
        return _fail('incomplete output must not show Top watch')
    if 'BULLISH scanner signal' in stale_text:
        return _fail('incomplete output must not show BULLISH scanner signal')
    if 'Previous-session / stale research only' not in stale_text:
        return _fail('incomplete output must use stale research header')

    with patch('backend.analytics.premarket_conviction._is_after_open', return_value=True), patch(
        'backend.analytics.premarket_conviction._is_live_market_routing', return_value=True,
    ):
        fresh_text = format_premarket_telegram(
            full=False,
            report=_base_report(fresh_ok=True),
            slot='premarket_top3',
        )
        if LIVE_MARKET_WATCH_TITLE not in fresh_text:
            return _fail('fresh market-hours output must use LIVE MARKET WATCH title')
        if 'DATA REFRESH INCOMPLETE' in fresh_text:
            return _fail('fresh scanner+market must not show DATA REFRESH INCOMPLETE')
        if 'Live watch:' not in fresh_text:
            return _fail('fresh market-hours output must show Live watch')

        partial_text = format_premarket_telegram(
            full=False,
            report=_base_report(fresh_ok=True, non_critical=['intel']),
            slot='premarket_top3',
        )
        if 'Context partially stale' not in partial_text:
            return _fail('non-critical stale should show partial stale note')

        if 'confirm after 9:15' in fresh_text.lower():
            return _fail('open setup must not say confirm after 9:15')
        if OPEN_CONFIRMED_ACTION not in fresh_text and 'confirmation already active' not in fresh_text.lower():
            return _fail('open setup missing post-9:15 action language')

    if crit and not ok and header:
        pass
    if non_crit and ok:
        pass

    print('LIVE_WATCH_CONSISTENCY_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
