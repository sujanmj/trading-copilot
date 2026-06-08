#!/usr/bin/env python3
"""Unit tests for broker intelligence extraction (Stage 48L)."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _fail(msg: str) -> int:
    print(f'BROKER_INTELLIGENCE_EXTRACTION_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.analytics.broker_intelligence import (
        classify_rating,
        detect_action,
        extract_broker_evidence_item,
        extract_target_prices,
        should_reject_item,
    )

    positive = extract_broker_evidence_item({
        'ticker': 'RELIANCE',
        'headline': 'Motilal Oswal upgrades Reliance to buy, raises target price to Rs 2800',
        'broker_source': 'Motilal Oswal',
        'published_at': '2026-06-08T10:00:00+05:30',
    })
    if not positive or positive.get('rating') != 'positive':
        return _fail('positive extraction failed')
    if positive.get('action') not in {'upgrade', 'target_raised', 'positive_rating'}:
        return _fail(f'unexpected positive action {positive.get("action")}')

    negative = extract_broker_evidence_item({
        'ticker': 'MCX',
        'headline': 'UBS downgrades MCX to sell, cuts target price',
        'broker_source': 'UBS',
        'published_at': '2026-06-08T09:00:00+05:30',
    })
    if not negative or negative.get('rating') != 'negative':
        return _fail('negative extraction failed')

    neutral = classify_rating({'headline': 'Broker maintains hold on INFY', 'ticker': 'INFY'})
    if neutral != 'neutral':
        return _fail(f'expected neutral got {neutral}')

    rejected, reason = should_reject_item({
        'ticker': 'BTC',
        'headline': 'Bitcoin surges to new high',
    })
    if not rejected or reason != 'crypto_only':
        return _fail('crypto-only rejection failed')

    rejected_us, _ = should_reject_item({
        'ticker': 'TCS',
        'headline': 'Nasdaq futures rise ahead of Fed rate decision',
    })
    if not rejected_us:
        return _fail('US-only without India impact should reject')

    tp, prev = extract_target_prices('raises target price to Rs 2800 from Rs 2600')
    if tp != 2800.0:
        return _fail(f'target price parse failed: {tp}')

    if detect_action('broker downgrades stock to sell') != 'downgrade':
        return _fail('downgrade detect failed')

    print('BROKER_INTELLIGENCE_EXTRACTION_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
