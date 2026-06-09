#!/usr/bin/env python3
"""Unit tests — /today must not add fake broker support from watchlist (Stage 48O)."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _fail(msg: str) -> int:
    print(f'BROKER_TODAY_NO_FAKE_SUPPORT_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.analytics.broker_intelligence import broker_decision_bullets
    from backend.analytics.stock_decision_engine import _build_telegram_message

    watchlist_cache = {
        'ok': True,
        'generated_at': '2026-05-27T10:00:00+05:30',
        'evidence_items': [{
            'ticker': 'BHARTIARTL',
            'headline': 'Stocks to watch: Bharti Airtel',
            'evidence_type': 'market_watchlist_mention',
            'counts_toward_consensus': False,
        }],
        'market_watchlist_mentions': [{'ticker': 'BHARTIARTL'}],
        'consensus_by_ticker': {},
        'tracked_ticker_names': ['BHARTIARTL'],
    }

    with patch('backend.analytics.broker_intelligence._load_cache', return_value=watchlist_cache):
        with patch('backend.analytics.broker_intelligence._cache_exists_on_disk', return_value=True):
            bullets = broker_decision_bullets('BHARTIARTL', mode='today')
            if bullets:
                return _fail('watchlist mention must not produce broker support bullets')
            msg = _build_telegram_message(
            mode='today',
            decision='WATCH_FOR_ENTRY',
            top_pick={
                'ticker': 'BHARTIARTL',
                'action': 'WATCH_FOR_ENTRY',
                'score': 55,
                'why': ['Scanner alignment'],
                'confirmation_needed': ['volume'],
                'risk': [],
            },
            avoid=[],
            )
            if 'Broker consensus supports' in msg:
                return _fail('today message must not add broker support from watchlist mention')

    print('BROKER_TODAY_NO_FAKE_SUPPORT_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
