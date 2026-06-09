#!/usr/bin/env python3
"""Unit tests — tomorrow mode surfaces live rejection warning (Stage 48R)."""

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
    print(f'TOMORROW_LIVE_REJECTION_WARNING_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.analytics.unified_decision_engine import (
        TOMORROW_LIVE_REJECTION_WARNING,
        apply_live_guard_to_payload,
        pick_live_safe_top,
    )

    registry = {'HDFCBANK': 'STRONG BEARISH — breakdown'}
    ranked = [
        {
            'ticker': 'HDFCBANK',
            'action': 'BUY_CANDIDATE',
            'score': 85,
            'risk': [],
            'why': ['Close report leader'],
            'supports': [],
        },
    ]

    top, decision, warnings = pick_live_safe_top(ranked, registry, mode='tomorrow')
    if not top or top.get('ticker') != 'HDFCBANK':
        return _fail(f'tomorrow may surface rejected leader for research, got {top!r}')
    if TOMORROW_LIVE_REJECTION_WARNING not in warnings:
        return _fail('tomorrow pick must append TOMORROW_LIVE_REJECTION_WARNING')
    if decision != 'BUY_CANDIDATE':
        return _fail(f'unexpected tomorrow decision {decision!r}')

    payload = {
        'ok': True,
        'mode': 'tomorrow',
        'ranked_candidates': ranked,
        'top_pick': ranked[0],
        'decision': 'BUY_CANDIDATE',
    }
    freshness_meta = {
        'report_stale': False,
        'scanner_fresh': True,
        'report_age_min': 30,
        'scanner_age_min': 2,
    }
    with patch(
        'backend.analytics.unified_decision_engine.build_live_rejection_set',
        return_value=registry,
    ), patch(
        'backend.analytics.unified_decision_engine.get_feed_freshness_meta',
        return_value=freshness_meta,
    ):
        guarded = apply_live_guard_to_payload(payload)

    snap_warnings = guarded.get('snapshot_warnings') or []
    if TOMORROW_LIVE_REJECTION_WARNING not in snap_warnings:
        return _fail('apply_live_guard_to_payload tomorrow must surface rejection warning')

    print('TOMORROW_LIVE_REJECTION_WARNING_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
