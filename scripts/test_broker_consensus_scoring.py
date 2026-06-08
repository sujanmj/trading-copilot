#!/usr/bin/env python3
"""Unit tests for broker consensus scoring (Stage 48L)."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _fail(msg: str) -> int:
    print(f'BROKER_CONSENSUS_SCORING_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.analytics.broker_intelligence import (
        consensus_label_from_score,
        score_ticker_consensus,
        suggested_action_from_label,
    )

    evidence = [
        {
            'ticker': 'RELIANCE',
            'rating': 'positive',
            'action': 'upgrade',
            'broker_house': 'House A',
            'headline': 'upgrade to buy',
            'published_at': '2026-06-08T10:00:00+05:30',
        },
        {
            'ticker': 'RELIANCE',
            'rating': 'positive',
            'action': 'target_raised',
            'broker_house': 'House B',
            'headline': 'target raised',
            'published_at': '2026-06-08T09:00:00+05:30',
        },
    ]
    scored = score_ticker_consensus(evidence)
    if scored.get('confidence_score', 0) < 80:
        return _fail(f'expected strong positive score, got {scored.get("confidence_score")}')
    if scored.get('consensus_label') != 'Strong Positive':
        return _fail(f'label mismatch {scored.get("consensus_label")}')
    if scored.get('suggested_action') != 'Watch for Confirmation':
        return _fail('suggested action must be Watch for Confirmation')

    down = score_ticker_consensus([
        {
            'ticker': 'MCX',
            'rating': 'negative',
            'action': 'downgrade',
            'broker_house': 'UBS',
            'headline': 'downgrade sell',
            'published_at': '2026-06-08T08:00:00+05:30',
        },
    ])
    if down.get('confidence_score', 100) >= 40:
        return _fail('downgrade should score below neutral band')
    if down.get('suggested_action') not in {'Wait', 'Avoid-Risk'}:
        return _fail(f'risk stance expected, got {down.get("suggested_action")}')

    if consensus_label_from_score(0, {'positive': 0, 'negative': 0, 'neutral': 0}) != 'Unknown':
        return _fail('empty counts should be Unknown')

    if 'buy' in suggested_action_from_label('Positive', 70).lower():
        return _fail('must never suggest buy')

    print('BROKER_CONSENSUS_SCORING_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
