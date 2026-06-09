#!/usr/bin/env python3
"""Unit tests — hard live rejection override (Stage 48R)."""

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
    print(f'LIVE_REJECTION_HARD_OVERRIDE_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.analytics.unified_decision_engine import (
        HARD_REJECTION_MSG,
        apply_live_guard_to_payload,
        apply_live_guard_to_ranked,
        build_live_rejection_set,
        clear_live_rejection_cache,
        pick_live_safe_top,
    )

    registry = {'ALPHA': 'STRONG BEARISH breakdown'}
    ranked = [
        {
            'ticker': 'ALPHA',
            'action': 'BUY_CANDIDATE',
            'score': 99,
            'risk': [],
            'why': ['Stale report leader'],
            'supports': [],
        },
        {
            'ticker': 'BETA',
            'action': 'BUY_CANDIDATE',
            'score': 70,
            'risk': [],
            'why': ['Live scanner alignment'],
            'supports': ['scanner'],
        },
    ]
    freshness_meta = {
        'report_stale': True,
        'scanner_fresh': True,
        'report_age_min': 720,
        'scanner_age_min': 3,
    }

    updated, top_pick, _warnings, decision = apply_live_guard_to_ranked(
        ranked,
        mode='today',
        registry=registry,
        freshness_meta=freshness_meta,
    )
    if updated[0].get('action') != 'AVOID':
        return _fail('live-rejected ticker must be hard-overridden to AVOID')
    if HARD_REJECTION_MSG not in ' '.join(updated[0].get('risk') or []):
        return _fail('hard rejection risk message missing from demoted row')
    if not top_pick or top_pick.get('ticker') != 'BETA':
        return _fail(f'pick_live_safe_top must skip rejected leader, got {top_pick!r}')
    if decision != 'BUY_CANDIDATE':
        return _fail(f'unexpected decision {decision!r}')

    top_only, decision_only, warn_only = pick_live_safe_top(
        updated,
        registry,
        mode='today',
    )
    if (top_only or {}).get('ticker') == 'ALPHA':
        return _fail('pick_live_safe_top must never return live-rejected ticker in today mode')

    clear_live_rejection_cache()
    with patch(
        'backend.analytics.unified_decision_engine._load_json',
        side_effect=lambda path: {
            'top_signals': [
                {
                    'ticker': 'GAMMA',
                    'direction': 'BEARISH',
                    'strength': 'STRONG',
                    'setup': 'breakdown',
                }
            ]
        }
        if path.name == 'scanner_data.json'
        else {},
    ):
        built = build_live_rejection_set(force_refresh=True)
    if 'GAMMA' not in built:
        return _fail('build_live_rejection_set must register bearish scanner tickers')

    payload = {
        'ok': True,
        'mode': 'today',
        'ranked_candidates': ranked,
        'top_pick': ranked[0],
        'decision': 'BUY_CANDIDATE',
    }
    with patch(
        'backend.analytics.unified_decision_engine.build_live_rejection_set',
        return_value=registry,
    ), patch(
        'backend.analytics.unified_decision_engine.get_feed_freshness_meta',
        return_value=freshness_meta,
    ):
        guarded = apply_live_guard_to_payload(payload)

    top = (guarded.get('top_pick') or {}).get('ticker')
    if top == 'ALPHA':
        return _fail('apply_live_guard_to_payload must hard-override rejected top_pick')
    if top != 'BETA':
        return _fail(f'expected BETA guarded top_pick got {top!r}')
    if not warn_only and guarded.get('snapshot_warnings'):
        pass

    print('LIVE_REJECTION_HARD_OVERRIDE_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
