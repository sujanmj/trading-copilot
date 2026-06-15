#!/usr/bin/env python3
"""Stage 50L — daily review tracks pending alerts instead of all zeros."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _fail(msg: str) -> int:
    print(f'DAILY_REVIEW_TRACKS_PENDING_ALERTS_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.analytics.eod_outcome_scoring import (
        format_daily_review_alert_lines,
        format_eod_telegram_message,
        summarize_alert_review_tracking,
    )

    tracking = {
        'premarket_watch_count': 1,
        'live_watch_count': 0,
        'open_setup_count': 2,
        'intraday_alert_count': 5,
        'pending_review_count': 5,
        'confirmed_count': 0,
        'rejected_count': 0,
        'wait_volume_count': 1,
        'entry_missed_count': 2,
    }
    summary = {'alerts_sent': 5, 'resolved': 0, 'date': '2026-06-16'}
    lines = format_daily_review_alert_lines(summary, tracking)
    if 'Intraday alerts: 5' not in lines[0]:
        return _fail(f'missing intraday count in {lines[0]!r}')
    if 'Pending review: 5' not in lines[1]:
        return _fail(f'missing pending review in {lines[1]!r}')
    if 'Resolved today: 0' not in lines[1]:
        return _fail(f'missing resolved today in {lines[1]!r}')

    msg = format_eod_telegram_message(summary, pending_meta={'pending_active': 0, 'expired': 0})
    if 'Pending review: 5' not in msg:
        return _fail('telegram daily review missing pending review line')
    if 'W0/L0/N0' in msg and 'Pending review' not in msg:
        return _fail('should not show bare W0/L0/N0 without pending context')

    fake_rows = [
        {'alert_type': 'intraday', 'reason_preview': 'ENTRY MISSED extended'},
        {'alert_type': 'intraday', 'reason_preview': 'WAIT FOR VOLUME'},
        {'alert_type': 'open', 'reason_preview': 'open setup'},
        {'alert_type': 'intraday', 'reason_preview': 'scanner'},
        {'alert_type': 'intraday', 'reason_preview': 'scanner'},
    ]
    with patch('backend.orchestration.alert_event_log.read_alert_events_for_date', return_value=fake_rows), \
         patch('backend.analytics.eod_outcome_scoring._query_telegram_alert_outcomes', return_value={'by_type': {}}):
        counts = summarize_alert_review_tracking('2026-06-16')
    if counts.get('intraday_alert_count') != 4:
        return _fail(f'expected 4 intraday alerts, got {counts.get("intraday_alert_count")}')

    print('DAILY_REVIEW_TRACKS_PENDING_ALERTS_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
