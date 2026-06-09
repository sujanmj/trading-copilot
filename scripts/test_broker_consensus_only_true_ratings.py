#!/usr/bin/env python3
"""Unit tests — consensus only from true broker ratings (Stage 48O)."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _fail(msg: str) -> int:
    print(f'BROKER_CONSENSUS_ONLY_TRUE_RATINGS_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.analytics.broker_intelligence import _apply_evidence_views

    payload = _apply_evidence_views({
        'ok': True,
        'generated_at': '2026-05-27T10:00:00+05:30',
        'evidence_items': [{
            'ticker': 'BHARTIARTL',
            'headline': 'Stocks to watch: Bharti Airtel among top picks',
            'broker_house': 'LiveMint',
            'rating': 'positive',
            'evidence_type': 'market_watchlist_mention',
            'counts_toward_consensus': False,
        }],
    })
    if payload.get('broker_rated_tickers'):
        return _fail('watchlist-only evidence must not create broker-rated tickers')
    if 'BHARTIARTL' in (payload.get('consensus_by_ticker') or {}):
        return _fail('watchlist mention must not appear in consensus_by_ticker')

    payload2 = _apply_evidence_views({
        'ok': True,
        'evidence_items': [{
            'ticker': 'RELIANCE',
            'headline': 'Analyst upgrades Reliance with target price raised to Rs 3200',
            'broker_house': 'Jefferies',
            'rating': 'positive',
            'action': 'upgrade',
            'evidence_type': 'upgrade_downgrade',
            'counts_toward_consensus': True,
        }],
    })
    if not payload2.get('broker_rated_tickers'):
        return _fail('true broker evidence must create broker-rated tickers')

    print('BROKER_CONSENSUS_ONLY_TRUE_RATINGS_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
