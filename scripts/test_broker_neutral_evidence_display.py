#!/usr/bin/env python3
"""Unit tests for broker neutral evidence display (Stage 48N)."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _fail(msg: str) -> int:
    print(f'BROKER_NEUTRAL_EVIDENCE_DISPLAY_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.analytics.broker_intelligence import format_broker_overview_telegram

    overview = {
        'ok': True,
        'generated_at': '2026-05-27T10:00:00+05:30',
        'freshness': {'status': 'fresh'},
        'tracked_tickers': 1,
        'tracked_ticker_names': ['NIFTY50'],
        'evidence_items': [{'ticker': 'NIFTY50', 'headline': 'Asia markets mixed', 'broker_house': 'Economic Times'}],
        'consensus_by_ticker': {
            'NIFTY50': {
                'ticker': 'NIFTY50',
                'consensus_label': 'Neutral',
                'confidence_score': 45,
                'suggested_action': 'Research Only',
                'evidence': [{'headline': 'Asia markets mixed', 'broker_house': 'Economic Times'}],
            },
        },
        'top_positive': [],
        'top_negative': [],
        'top_neutral': [{
            'ticker': 'NIFTY50',
            'consensus_label': 'Neutral',
            'confidence_score': 45,
            'evidence': [{'headline': 'Asia markets mixed', 'broker_house': 'Economic Times'}],
        }],
    }

    with patch('backend.analytics.broker_intelligence.get_broker_intel_overview', return_value=overview):
        with patch('backend.analytics.broker_intelligence._cache_exists_on_disk', return_value=True):
            text = format_broker_overview_telegram()

    if 'Neutral / Other evidence' not in text:
        return _fail('overview must include Neutral / Other evidence section')
    if 'NIFTY50' not in text:
        return _fail('overview must show tracked ticker NIFTY50')
    if 'None in cache' in text:
        return _fail('must not hide tracked neutral ticker behind None in cache')

    print('BROKER_NEUTRAL_EVIDENCE_DISPLAY_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
