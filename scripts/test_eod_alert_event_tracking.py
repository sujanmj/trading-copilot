#!/usr/bin/env python3
"""Unit tests for EOD alert event log tracking (Stage 46I)."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)


def _fail(msg: str) -> int:
    print(f'EOD_ALERT_EVENT_TRACKING_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.analytics.eod_outcome_scoring import compute_eod_outcome_summary, format_eod_telegram_message
    from backend.orchestration.alert_event_log import (
        ALERT_LOG_FILE,
        log_alert_event,
        read_alert_events_for_date,
        summarize_alert_events_for_date,
    )

    review_date = '2026-06-05'
    if ALERT_LOG_FILE.is_file():
        backup = ALERT_LOG_FILE.read_text(encoding='utf-8')
    else:
        backup = ''

    try:
        ALERT_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        ALERT_LOG_FILE.write_text('', encoding='utf-8')

        entry = log_alert_event(
            category='INTRADAY_OPPORTUNITY',
            tickers='WIPRO',
            direction='BULLISH',
            score=0.78,
            price_at_alert=450.0,
            volume_at_alert=1.2,
            reason='open setup WIPRO',
            timestamp=f'{review_date}T09:35:00+05:30',
        )
        for field in ('timestamp', 'alert_type', 'tickers', 'direction', 'score', 'reason_hash'):
            if field not in entry:
                return _fail(f'log entry missing {field}')
        if entry.get('alert_type') != 'open':
            return _fail(f'expected alert_type open, got {entry.get("alert_type")}')

        rows = read_alert_events_for_date(review_date)
        if len(rows) != 1:
            return _fail(f'expected 1 log row, got {len(rows)}')

        meta = summarize_alert_events_for_date(review_date)
        if meta.get('alerts_sent', 0) != 1:
            return _fail('summarize alerts_sent wrong')

        empty_pred = {'counts': {'WIN': 0, 'LOSS': 0, 'NEUTRAL': 0, 'PARTIAL': 0, 'EXPIRED': 0, 'PENDING': 0}, 'rows': []}
        empty_tg = {'by_type': {}, 'rows': [], 'price_missing': True}

        with patch('backend.analytics.eod_outcome_scoring._query_prediction_outcomes', return_value=empty_pred):
            with patch('backend.analytics.eod_outcome_scoring._query_telegram_alert_outcomes', return_value=empty_tg):
                summary = compute_eod_outcome_summary(review_date)

        if summary.get('alerts_sent', 0) < 1:
            return _fail('EOD summary should read alert_event_log alerts_sent')
        if summary.get('resolved', 0) != 0:
            return _fail('resolved should stay 0 without price outcomes')

        msg = format_eod_telegram_message(summary)
        if 'Alerts sent:' not in msg:
            return _fail('EOD message must show Alerts sent when log has entries')
        if 'Resolved: 0' in msg:
            return _fail('must not show Resolved: 0 when alerts were sent')
        if 'Pending price data' not in msg:
            return _fail('missing Pending price data line')

        engine_src = (PROJECT_ROOT / 'backend/orchestration/telegram_alert_engine.py').read_text(encoding='utf-8')
        if 'alert_event_log' not in engine_src:
            return _fail('telegram_alert_engine missing alert_event_log wiring')
    finally:
        if backup:
            ALERT_LOG_FILE.write_text(backup, encoding='utf-8')
        elif ALERT_LOG_FILE.is_file():
            ALERT_LOG_FILE.unlink()

    print('EOD_ALERT_EVENT_TRACKING_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
