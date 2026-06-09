#!/usr/bin/env python3
"""Unit tests — guarded top_pick never appears in avoid list (Stage 48R)."""

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
    print(f'FULL_SNAPSHOT_NO_TOP_CANDIDATE_IN_AVOID_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.analytics.unified_decision_engine import (
        apply_live_guard_to_payload,
        begin_unified_snapshot,
        end_unified_snapshot,
    )

    registry = {'AVANTIFEED': 'STRONG BEARISH — premarket avoid'}
    freshness_meta = {
        'report_stale': True,
        'scanner_fresh': True,
        'report_age_min': 660,
        'scanner_age_min': 2,
    }
    payload = {
        'ok': True,
        'mode': 'today',
        'ranked_candidates': [
            {
                'ticker': 'AVANTIFEED',
                'action': 'BUY_CANDIDATE',
                'score': 90,
                'risk': [],
                'why': ['Stale close report'],
                'supports': [],
            },
            {
                'ticker': 'RELIANCE',
                'action': 'BUY_CANDIDATE',
                'score': 72,
                'risk': [],
                'why': ['Live scanner'],
                'supports': ['scanner'],
            },
        ],
        'top_pick': {'ticker': 'AVANTIFEED', 'action': 'BUY_CANDIDATE', 'score': 90},
        'decision': 'BUY_CANDIDATE',
    }

    with patch(
        'backend.analytics.unified_decision_engine.build_live_rejection_set',
        return_value=registry,
    ), patch(
        'backend.analytics.unified_decision_engine.get_feed_freshness_meta',
        return_value=freshness_meta,
    ):
        begin_unified_snapshot()
        try:
            guarded = apply_live_guard_to_payload(payload)
        finally:
            end_unified_snapshot()

    top_ticker = str((guarded.get('top_pick') or {}).get('ticker') or '').upper()
    if not top_ticker:
        return _fail('guarded snapshot must retain a top_pick')
    if top_ticker == 'AVANTIFEED':
        return _fail('top_pick must not be live-rejected AVANTIFEED')

    avoid_tickers = {
        str(row.get('ticker') or '').upper()
        for row in guarded.get('avoid') or []
        if row.get('action') == 'AVOID'
    }
    if top_ticker in avoid_tickers:
        return _fail(f'top_pick {top_ticker} must not also appear in avoid list')

    ranked_top = next(
        (
            r for r in guarded.get('ranked_candidates') or []
            if str(r.get('ticker') or '').upper() == top_ticker
        ),
        None,
    )
    if not ranked_top or ranked_top.get('action') == 'AVOID':
        return _fail('top_pick ticker must remain a non-AVOID ranked row')

    print('FULL_SNAPSHOT_NO_TOP_CANDIDATE_IN_AVOID_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
