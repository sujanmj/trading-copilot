#!/usr/bin/env python3
"""Unit tests for scanner session-date guard (Stage 47D)."""

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
NOW = datetime(2026, 6, 8, 8, 0, tzinfo=IST)


def _fail(msg: str) -> int:
    print(f'SCANNER_SESSION_DATE_GUARD_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.orchestration.alert_freshness_gate import (
        annotate_candidate_session,
        extract_session_date_from_source,
        get_current_india_trading_date,
        is_current_trading_session,
    )
    from backend.analytics.premarket_conviction import _annotate_setup_row, _rank_top_setups

    current = get_current_india_trading_date(NOW)
    old_data = {'generated_at': '2026-06-02T10:43:00+00:00', 'last_updated': '2026-06-02T10:43:00+00:00'}
    old_session = extract_session_date_from_source(old_data)
    if old_session != '2026-06-02':
        return _fail(f'expected 2026-06-02 session date, got {old_session}')
    if is_current_trading_session(old_session, NOW):
        return _fail('old session must not be current trading session')
    if not is_current_trading_session(current, NOW):
        return _fail('today must be current trading session')

    row = annotate_candidate_session(
        {'ticker': 'TEST', 'setup': 'WATCH', 'score': 80},
        source='scanner',
        source_data=old_data,
        now=NOW,
    )
    for field in ('data_timestamp', 'session_date', 'source_age_minutes', 'is_current_trading_session'):
        if field not in row:
            return _fail(f'missing candidate field: {field}')
    if row.get('is_current_trading_session'):
        return _fail('old scanner data must not be current session')
    if not row.get('previous_session_research'):
        return _fail('old session should be flagged previous_session_research')

    annotated = _annotate_setup_row(
        {'ticker': 'OLD', 'setup': 'BULLISH scanner signal', 'score': 90, 'source': 'scanner'},
        source='scanner',
        source_data=old_data,
    )
    if annotated.get('score', 0) > 50:
        return _fail('previous-session candidate score must be <= 50')
    if annotated.get('tier_cap') != 'not_top3':
        return _fail('previous-session candidate must not qualify for top3')

    ranked = _rank_top_setups([
        {'ticker': 'OLD', 'score': 45, 'tier_cap': 'not_top3'},
        {'ticker': 'NEW', 'score': 70},
    ])
    if ranked[0].get('ticker') != 'NEW':
        return _fail('top rank should prefer current-session eligible setup')

    print('SCANNER_SESSION_DATE_GUARD_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
