#!/usr/bin/env python3
"""Stage 50Z — scanner fresh + report stale uses live-scanner-only wording."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _fail(msg: str) -> int:
    print(f'REFRESH_INCOMPLETE_WORDING_SCANNER_FRESH_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.orchestration.alert_freshness_gate import (
        PREMARKET_INCOMPLETE_HEADER,
        PREMARKET_OLD_SESSION_NOTE,
        REPORT_CACHE_STALE_LIVE_SCANNER_HEADER,
        REPORT_CACHE_STALE_LIVE_SCANNER_NOTE,
        _resolve_premarket_stale_header,
    )

    fresh_meta = {
        'scanner_fresh': True,
        'report_stale': True,
        'report_suppressed': False,
    }
    with patch('backend.analytics.unified_decision_engine.get_feed_freshness_meta', return_value=fresh_meta):
        header = _resolve_premarket_stale_header(['intel', 'watchlist'])

    if header != REPORT_CACHE_STALE_LIVE_SCANNER_HEADER:
        return _fail(f'expected live scanner header, got {header!r}')
    if 'DATA REFRESH INCOMPLETE' in header:
        return _fail('scanner-fresh path must not use DATA REFRESH INCOMPLETE header')

    scanner_stale_meta = {'scanner_fresh': False, 'report_stale': True, 'report_suppressed': True}
    with patch('backend.analytics.unified_decision_engine.get_feed_freshness_meta', return_value=scanner_stale_meta):
        header_stale = _resolve_premarket_stale_header(['scanner', 'intel'])

    if header_stale != PREMARKET_INCOMPLETE_HEADER:
        return _fail('scanner-stale path must keep incomplete header')

    from backend.analytics.premarket_conviction import format_premarket_telegram

    report = {
        'freshness_ok': False,
        'freshness_header': REPORT_CACHE_STALE_LIVE_SCANNER_HEADER,
        'hard_stale_lock': False,
        'riskoff_premarket': False,
        'non_critical_stale_keys': [],
        'top_setups': [],
        'deferred_weak_volume': [],
        'avoid': [],
        'market_bias': 'NEUTRAL',
        'market_mode': {'market_mode': 'INDIA_PREMARKET_MODE'},
        'cache_stale_message': '',
        'cache_age_hours': 0,
        'previous_session_movers': [],
        'weekend_research_mode': False,
    }
    with patch('backend.analytics.premarket_conviction._is_weekend_holiday_research', return_value=False), \
         patch('backend.analytics.premarket_conviction._is_live_market_routing', return_value=False):
        text = format_premarket_telegram(full=False, report=report, slot='premarket_top3')

    if REPORT_CACHE_STALE_LIVE_SCANNER_NOTE not in text:
        return _fail('premarket telegram must show live scanner note')
    if PREMARKET_OLD_SESSION_NOTE in text:
        return _fail('old session note must not appear when scanner is fresh')

    print('REFRESH_INCOMPLETE_WORDING_SCANNER_FRESH_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
