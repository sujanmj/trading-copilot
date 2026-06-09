#!/usr/bin/env python3
"""Unit tests — broker overview telegram headline truncation (Stage 48R)."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

os.environ.setdefault('DISABLE_TELEGRAM', '1')
os.environ.setdefault('DISABLE_TELEGRAM_SENDS', '1')


def _fail(msg: str) -> int:
    print(f'BROKER_OVERVIEW_HEADLINE_CLEANUP_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.analytics.broker_intelligence import (
        _truncate_headline,
        format_broker_overview_telegram,
    )

    long_headline = (
        'Stocks to watch: Adani Enterprises, Bharti Airtel, RVNL, Vodafone Idea '
        'among key stocks in focus for the session ahead with sector rotation cues'
    )
    trimmed = _truncate_headline(long_headline, 110)
    if not trimmed.endswith('…'):
        return _fail('truncated headline must end with ellipsis')
    if len(trimmed) > 110:
        return _fail(f'truncated headline exceeds 110 chars: {len(trimmed)}')

    mock_overview = {
        'cache_missing': False,
        'freshness': {'status': 'fresh'},
        'broker_rated_tickers': 2,
        'market_mention_count': 1,
        'top_positive': [
            {
                'ticker': 'RELIANCE',
                'consensus_label': 'Buy',
                'confidence_score': 72,
                'suggested_action': 'Watch',
            }
        ],
        'top_negative': [],
        'market_watchlist_mentions': [
            {
                'ticker': 'IDEA',
                'source': 'Economic Times',
                'headline': long_headline,
            }
        ],
        'external_evidence': [
            {
                'ticker': 'TCS',
                'source': 'Motilal Oswal',
                'headline': long_headline,
            }
        ],
        'evidence_items': [],
        'consensus_by_ticker': {},
    }

    with patch(
        'backend.analytics.broker_intelligence.get_broker_intel_overview',
        return_value=mock_overview,
    ):
        text = format_broker_overview_telegram()

    if long_headline in text:
        return _fail('broker overview must not emit untruncated long headlines')
    if trimmed not in text:
        return _fail('broker overview must include truncated headline text')
    if 'Broker Intelligence' not in text:
        return _fail('broker overview telegram header missing')

    print('BROKER_OVERVIEW_HEADLINE_CLEANUP_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
