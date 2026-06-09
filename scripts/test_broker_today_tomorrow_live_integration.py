#!/usr/bin/env python3
"""Unit tests for live broker today/tomorrow integration (Stage 48M)."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _fail(msg: str) -> int:
    print(f'BROKER_TODAY_TOMORROW_LIVE_INTEGRATION_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.analytics.broker_intelligence import broker_decision_bullets
    from backend.analytics.stock_decision_engine import _build_telegram_message

    cache = {
        'ok': True,
        'generated_at': '2026-05-27T10:00:00+05:30',
        'evidence_items': [{'ticker': 'RELIANCE', 'headline': 'Upgrade'}],
        'consensus_by_ticker': {
            'RELIANCE': {
                'consensus_label': 'Positive',
                'confidence_score': 72,
                'suggested_action': 'Watch for Confirmation',
            },
        },
        'freshness': {'status': 'fresh'},
    }

    with patch('backend.analytics.broker_intelligence._load_cache', return_value=cache):
        msg = _build_telegram_message(
            mode='tomorrow',
            decision='WATCH_FOR_ENTRY',
            top_pick={
                'ticker': 'RELIANCE',
                'action': 'WATCH_FOR_ENTRY',
                'score': 55,
                'why': ['Scanner alignment'],
                'confirmation_needed': ['volume'],
                'risk': [],
            },
            avoid=[],
        )
        if 'Broker consensus supports RELIANCE' not in msg:
            return _fail('tomorrow message must include broker support when cache evidence exists')

        if broker_decision_bullets('UNKNOWN', mode='tomorrow'):
            return _fail('unknown ticker must not get broker line')

    empty_cache = {
        'ok': True,
        'generated_at': '2026-05-27T10:00:00+05:30',
        'evidence_items': [],
        'consensus_by_ticker': {},
    }
    with patch('backend.analytics.broker_intelligence._load_cache', return_value=empty_cache):
        if broker_decision_bullets('RELIANCE', mode='today'):
            return _fail('must not add fake broker line when cache has no evidence')

    print('BROKER_TODAY_TOMORROW_LIVE_INTEGRATION_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
