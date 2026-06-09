#!/usr/bin/env python3
"""Unit tests for broker intelligence cache model (Stage 48L)."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _fail(msg: str) -> int:
    print(f'BROKER_CACHE_MODEL_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    src = (PROJECT_ROOT / 'backend/analytics/broker_intelligence.py').read_text(encoding='utf-8')
    for key in (
        'consensus_by_ticker',
        'top_upgrades',
        'top_downgrades',
        'target_price_changes',
        'broker_mentions',
        'evidence_items',
        'stale_reason',
        'consensus_label',
        'confidence_score',
        'suggested_action',
    ):
        if key not in src:
            return _fail(f'broker_intelligence.py missing {key!r}')

    from backend.analytics.broker_intelligence import (
        CACHE_FILE,
        STAGE,
        build_broker_intelligence_cache,
    )

    if STAGE != '48U':
        return _fail(f'expected stage 48U got {STAGE}')
    if CACHE_FILE.name != 'broker_intelligence_cache.json':
        return _fail('wrong cache filename')

    payload = build_broker_intelligence_cache()
    for field in (
        'generated_at', 'freshness', 'source_counts', 'consensus_by_ticker',
        'top_upgrades', 'top_downgrades', 'target_price_changes',
        'broker_mentions', 'evidence_items',
    ):
        if field not in payload:
            return _fail(f'cache payload missing {field!r}')

    sample = next(iter((payload.get('consensus_by_ticker') or {}).values()), None)
    if sample:
        for field in (
            'consensus_label', 'confidence_score', 'broker_counts',
            'latest_rating', 'latest_action', 'freshness', 'evidence', 'suggested_action',
        ):
            if field not in sample:
                return _fail(f'per-ticker model missing {field!r}')

    print('BROKER_CACHE_MODEL_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
