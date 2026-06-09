#!/usr/bin/env python3
"""Unit tests for unified decision live-guard consistency (Stage 48Q)."""

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
    print(f'DECISION_CANDIDATE_CONSISTENCY_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.analytics.unified_decision_engine import (
        LIVE_REJECTION_MSG,
        apply_live_guard_to_payload,
        apply_live_guard_to_ranked,
    )

    registry = {'RISKY': 'STRONG BEARISH breakdown'}
    ranked = [
        {
            'ticker': 'RISKY',
            'action': 'BUY_CANDIDATE',
            'score': 92,
            'risk': [],
            'why': ['Stale report pick'],
            'supports': [],
        },
        {
            'ticker': 'CLEAN',
            'action': 'BUY_CANDIDATE',
            'score': 78,
            'risk': [],
            'why': ['Live scanner alignment'],
            'supports': ['scanner'],
        },
    ]

    freshness_meta = {
        'report_stale': True,
        'scanner_fresh': True,
        'report_age_min': 660,
        'scanner_age_min': 2,
    }
    updated, top_pick, _warnings, decision = apply_live_guard_to_ranked(
        ranked,
        mode='today',
        registry=registry,
        freshness_meta=freshness_meta,
    )
    if updated[0].get('action') != 'AVOID':
        return _fail('avoid-registry ticker must be demoted to AVOID')
    if LIVE_REJECTION_MSG not in ' '.join(updated[0].get('risk') or []):
        return _fail('avoid-registry ticker must include live rejection risk')
    if not top_pick or top_pick.get('ticker') != 'CLEAN':
        return _fail(f'expected CLEAN top_pick got {top_pick!r}')
    if decision != 'BUY_CANDIDATE':
        return _fail(f'unexpected decision {decision!r}')

    payload = {
        'ok': True,
        'mode': 'today',
        'ranked_candidates': ranked,
        'top_pick': ranked[0],
        'decision': 'BUY_CANDIDATE',
    }
    with patch(
        'backend.analytics.unified_decision_engine.load_live_avoid_registry',
        return_value=registry,
    ), patch(
        'backend.analytics.unified_decision_engine.get_feed_freshness_meta',
        return_value=freshness_meta,
    ):
        guarded = apply_live_guard_to_payload(payload)

    top = (guarded.get('top_pick') or {}).get('ticker')
    if top == 'RISKY':
        return _fail('apply_live_guard_to_payload must not keep avoid-registry ticker as top_pick')
    if top != 'CLEAN':
        return _fail(f'expected guarded top_pick CLEAN got {top!r}')

    print('DECISION_CANDIDATE_CONSISTENCY_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
