#!/usr/bin/env python3
"""Unit tests for market mentions section in /broker (Stage 48O)."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _fail(msg: str) -> int:
    print(f'BROKER_MARKET_MENTIONS_SECTION_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.analytics.broker_intelligence import format_broker_overview_telegram

    overview = {
        'ok': True,
        'freshness': {'status': 'fresh'},
        'broker_rated_tickers': 0,
        'market_mention_count': 1,
        'top_positive': [],
        'top_negative': [],
        'market_watchlist_mentions': [{
            'ticker': 'BHARTIARTL',
            'source': 'LiveMint',
            'headline': 'Stocks to watch: Bharti Airtel, RVNL',
        }],
        'external_evidence': [],
    }
    with patch('backend.analytics.broker_intelligence.get_broker_intel_overview', return_value=overview):
        with patch('backend.analytics.broker_intelligence._cache_exists_on_disk', return_value=True):
            text = format_broker_overview_telegram()

    if 'Market watchlist mentions' not in text:
        return _fail('overview must include Market watchlist mentions section')
    if 'No broker/analyst ratings found' not in text:
        return _fail('watchlist-only cache must say no broker ratings found')
    if 'BHARTIARTL' not in text:
        return _fail('watchlist ticker must be visible')
    if 'market mentions are not broker ratings' not in text.lower():
        return _fail('must clarify market mentions are not broker ratings')

    print('BROKER_MARKET_MENTIONS_SECTION_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
