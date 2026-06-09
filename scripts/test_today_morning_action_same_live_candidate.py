#!/usr/bin/env python3
"""Unit tests — today/morning/action_plan share same live-safe top (Stage 48R)."""

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
    print(f'TODAY_MORNING_ACTION_SAME_LIVE_CANDIDATE_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def _payload(mode: str) -> dict:
    return {
        'ok': True,
        'mode': mode,
        'ranked_candidates': [
            {
                'ticker': 'AVANTIFEED',
                'action': 'BUY_CANDIDATE',
                'score': 88,
                'risk': [],
                'why': ['Stale close report'],
                'supports': [],
            },
            {
                'ticker': 'INFY',
                'action': 'BUY_CANDIDATE',
                'score': 81,
                'risk': [],
                'why': ['Live scanner alignment'],
                'supports': ['scanner'],
            },
        ],
        'top_pick': {'ticker': 'AVANTIFEED', 'action': 'BUY_CANDIDATE', 'score': 88},
        'decision': 'BUY_CANDIDATE',
    }


def main() -> int:
    from backend.analytics.unified_decision_engine import apply_live_guard_to_payload

    registry = {'AVANTIFEED': 'STRONG BEARISH — live breakdown'}
    freshness_meta = {
        'report_stale': True,
        'scanner_fresh': True,
        'report_age_min': 540,
        'scanner_age_min': 2,
    }

    picks: dict[str, str] = {}
    with patch(
        'backend.analytics.unified_decision_engine.build_live_rejection_set',
        return_value=registry,
    ), patch(
        'backend.analytics.unified_decision_engine.get_feed_freshness_meta',
        return_value=freshness_meta,
    ):
        for mode in ('today', 'morning', 'action_plan'):
            guarded = apply_live_guard_to_payload(_payload(mode))
            top = str((guarded.get('top_pick') or {}).get('ticker') or '').upper()
            if not top:
                return _fail(f'{mode} must retain a live-safe top_pick')
            if top == 'AVANTIFEED':
                return _fail(f'{mode} must not keep AVANTIFEED as top')
            picks[mode] = top

    unique = set(picks.values())
    if len(unique) != 1:
        return _fail(f'today/morning/action_plan must agree on top pick: {picks!r}')
    if picks['today'] != 'INFY':
        return _fail(f'expected INFY across strict modes got {picks!r}')

    print('TODAY_MORNING_ACTION_SAME_LIVE_CANDIDATE_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
