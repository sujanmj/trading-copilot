#!/usr/bin/env python3
"""Unit tests for broker evidence_type classification (Stage 48O)."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _fail(msg: str) -> int:
    print(f'BROKER_EVIDENCE_TYPE_CLASSIFICATION_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.analytics.broker_intelligence import (
        CONSENSUS_EVIDENCE_TYPES,
        classify_evidence_type,
        extract_broker_evidence_item,
    )

    watch = classify_evidence_type(
        {'headline': 'Stocks to watch: Bharti Airtel, RVNL', 'source': 'LiveMint'},
        text='Stocks to watch: Bharti Airtel, RVNL',
    )
    if watch != 'market_watchlist_mention':
        return _fail(f'watchlist headline must be market_watchlist_mention, got {watch!r}')

    upgrade = classify_evidence_type(
        {'headline': 'Jefferies upgrades Reliance to buy, target price Rs 3200'},
        text='Jefferies upgrades Reliance to buy, target price Rs 3200',
    )
    if upgrade not in CONSENSUS_EVIDENCE_TYPES:
        return _fail(f'upgrade headline must count as consensus evidence, got {upgrade!r}')

    item = extract_broker_evidence_item({
        'ticker': 'BHARTIARTL',
        'headline': 'Stocks to watch: Bharti Airtel among key stocks',
        'source': 'LiveMint',
        'collector_source': 'news_feed',
    })
    if not item or item.get('evidence_type') != 'market_watchlist_mention':
        return _fail('extracted watchlist item must have market_watchlist_mention type')
    if item.get('counts_toward_consensus'):
        return _fail('watchlist mention must not count toward consensus')

    print('BROKER_EVIDENCE_TYPE_CLASSIFICATION_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
