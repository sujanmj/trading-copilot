#!/usr/bin/env python3
"""Unit tests for EOD outcome scoring (Stage 46H)."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)


def _fail(msg: str) -> int:
    print(f'EOD_OUTCOME_SCORING_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.analytics.eod_outcome_scoring import (
        compute_eod_outcome_summary,
        format_eod_telegram_message,
    )

    mock_pred = {
        'counts': {'WIN': 3, 'LOSS': 2, 'NEUTRAL': 1, 'PARTIAL': 1, 'EXPIRED': 5, 'PENDING': 0},
        'rows': [
            {'ticker': 'TATA', 'verdict': 'WIN', 'pct': 4.2, 'alert_type': 'prediction'},
            {'ticker': 'RELIANCE', 'verdict': 'LOSS', 'pct': -3.1, 'alert_type': 'prediction'},
        ],
    }
    mock_tg = {
        'by_type': {
            'open_setup': {'WIN': 1, 'LOSS': 0, 'NEUTRAL': 0, 'PARTIAL': 0, 'PENDING': 0},
            'intraday': {'WIN': 0, 'LOSS': 1, 'NEUTRAL': 0, 'PARTIAL': 0, 'PENDING': 0},
        },
        'rows': [],
        'price_missing': False,
    }

    with patch('backend.analytics.eod_outcome_scoring._query_prediction_outcomes', return_value=mock_pred):
        with patch('backend.analytics.eod_outcome_scoring._query_telegram_alert_outcomes', return_value=mock_tg):
            summary = compute_eod_outcome_summary('2026-06-03')

    if summary.get('resolved', 0) <= 0:
        return _fail('resolved should be > 0 with mock data')
    if summary.get('wins', 0) == 0 and summary.get('losses', 0) == 0:
        return _fail('W/L should not be zero when resolved > 0')
    if 'W0/L0/N0' in format_eod_telegram_message(summary):
        return _fail('telegram message shows W0/L0/N0 incorrectly')

    alerts_summary = {
        'date': '2026-06-03',
        'alerts_sent': 4,
        'alerts_tracked': 4,
        'alerts_scorable': 3,
        'alerts_pending_score': 3,
        'resolved': 0,
        'wins': 0,
        'losses': 0,
        'data_available': False,
        'by_alert_type': {},
        'best': [],
        'worst': [],
    }
    alerts_msg = format_eod_telegram_message(alerts_summary)
    if 'Alerts tracked' not in alerts_msg:
        return _fail('alerts sent today should show tracked line not Resolved 0')
    if 'Resolved: 0' in alerts_msg:
        return _fail('should not show Resolved: 0 when alerts were sent')

    msg = format_eod_telegram_message(summary, pending_meta={'pending_active': 2, 'expired': 1})
    for needle in ('DAILY REVIEW', 'EOD Resolution', 'Open setups', 'Intraday', 'Emergency macro'):
        if needle not in msg:
            return _fail(f'message missing {needle}')

    empty_tg = {'by_type': {}, 'rows': [], 'price_missing': True}
    empty_pred = {'counts': {'WIN': 0, 'LOSS': 0, 'NEUTRAL': 0, 'PARTIAL': 0, 'EXPIRED': 0, 'PENDING': 0}, 'rows': []}
    with patch('backend.analytics.eod_outcome_scoring._query_prediction_outcomes', return_value=empty_pred):
        with patch('backend.analytics.eod_outcome_scoring._query_telegram_alert_outcomes', return_value=empty_tg):
            empty_summary = compute_eod_outcome_summary('2026-06-03')
    empty_msg = format_eod_telegram_message(empty_summary)
    if 'Outcome pending' not in empty_msg and 'price data unavailable' not in empty_msg.lower():
        return _fail('missing unavailable outcome message when no data')

    lc_src = (PROJECT_ROOT / 'backend/lifecycle/prediction_lifecycle_engine.py').read_text(encoding='utf-8')
    if 'eod_outcome_scoring' not in lc_src:
        return _fail('prediction_lifecycle_engine not wired to eod_outcome_scoring')

    print('EOD_OUTCOME_SCORING_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
