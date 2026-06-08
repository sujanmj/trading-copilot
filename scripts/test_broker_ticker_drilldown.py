#!/usr/bin/env python3
"""Unit tests for broker ticker drilldown (Stage 48L)."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _fail(msg: str) -> int:
    print(f'BROKER_TICKER_DRILLDOWN_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.analytics.broker_intelligence import (
        format_broker_ticker_telegram,
        get_broker_intel_ticker,
    )

    sample_cache = {
        'ok': True,
        'consensus_by_ticker': {
            'RELIANCE': {
                'ticker': 'RELIANCE',
                'consensus_label': 'Positive',
                'confidence_score': 72,
                'suggested_action': 'Watch for Confirmation',
                'freshness': 'fresh',
                'broker_counts': {'positive': 2, 'neutral': 0, 'negative': 0},
                'latest_action': 'upgrade',
                'target_price': 2800,
                'evidence': [
                    {
                        'ticker': 'RELIANCE',
                        'broker_house': 'Motilal Oswal',
                        'headline': 'Upgrade to buy',
                        'rating': 'positive',
                    },
                ],
            },
        },
        'freshness': {'status': 'fresh'},
        'impact_today': [{'ticker': 'RELIANCE', 'impact': 'supportive_evidence', 'suggested_action': 'Watch for Confirmation'}],
        'impact_tomorrow': [],
        'disclaimer': 'External broker/app evidence — not our final prediction.',
    }

    with patch('backend.analytics.broker_intelligence._load_cache', return_value=sample_cache):
        detail = get_broker_intel_ticker('RELIANCE', cache_only=True, lite=True)
        if not detail.get('found'):
            return _fail('RELIANCE should be found in sample cache')
        if detail.get('consensus', {}).get('consensus_label') != 'Positive':
            return _fail('consensus label mismatch')
        if not detail.get('evidence'):
            return _fail('lite drilldown must include evidence')

        text = format_broker_ticker_telegram('RELIANCE')
        for needle in ('RELIANCE', 'Consensus', 'Evidence', 'not a trade signal'):
            if needle not in text:
                return _fail(f'telegram drilldown missing {needle!r}')

        missing = get_broker_intel_ticker('ZZZZZZ', cache_only=True, lite=True)
        if missing.get('found'):
            return _fail('unknown ticker should not be found')

    api_src = (PROJECT_ROOT / 'backend/api/api_server.py').read_text(encoding='utf-8')
    if '/api/brokers/ticker/{ticker}' not in api_src:
        return _fail('ticker API route missing')

    print('BROKER_TICKER_DRILLDOWN_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
