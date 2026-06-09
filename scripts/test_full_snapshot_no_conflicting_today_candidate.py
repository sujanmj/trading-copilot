#!/usr/bin/env python3
"""Unit tests — /full unified snapshot rejects premarket avoid conflicts (Stage 48Q)."""

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
    print(f'FULL_SNAPSHOT_NO_CONFLICTING_TODAY_CANDIDATE_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def _today_payload() -> dict:
    return {
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


def main() -> int:
    from backend.analytics.unified_decision_engine import (
        apply_live_guard_to_payload,
        begin_unified_snapshot,
        end_unified_snapshot,
        note_snapshot_pick,
        snapshot_consistency_warnings,
    )
    from backend.telegram import telegram_analysis_bot as tab

    premarket_avoid = {'AVANTIFEED': 'STRONG BEARISH — premarket avoid'}
    freshness_meta = {
        'report_stale': True,
        'scanner_fresh': True,
        'report_age_min': 660,
        'scanner_age_min': 2,
    }

    snapshot_started = False
    snapshot_ended = False

    def _track_begin() -> None:
        nonlocal snapshot_started
        snapshot_started = True
        begin_unified_snapshot()

    def _track_end() -> None:
        nonlocal snapshot_ended
        snapshot_ended = True
        end_unified_snapshot()

    with patch(
        'backend.analytics.unified_decision_engine.load_live_avoid_registry',
        return_value=premarket_avoid,
    ), patch(
        'backend.analytics.unified_decision_engine.get_feed_freshness_meta',
        return_value=freshness_meta,
    ), patch(
        'backend.analytics.unified_decision_engine.begin_unified_snapshot',
        side_effect=_track_begin,
    ), patch(
        'backend.analytics.unified_decision_engine.end_unified_snapshot',
        side_effect=_track_end,
    ), patch.object(tab, 'handle_analysis_command', return_value=[{'ok': True, 'text': 'mock'}]), patch.object(
        tab,
        'send_analysis_message',
        return_value={'ok': True, 'text': 'mock'},
    ):
        tab._handle_full_snapshot(dry_run=True)

    if not snapshot_started or not snapshot_ended:
        return _fail('/full must wrap steps in begin/end unified snapshot')

    with patch(
        'backend.analytics.unified_decision_engine.load_live_avoid_registry',
        return_value=premarket_avoid,
    ), patch(
        'backend.analytics.unified_decision_engine.get_feed_freshness_meta',
        return_value=freshness_meta,
    ):
        begin_unified_snapshot()
        try:
            today = apply_live_guard_to_payload(_today_payload())
            action = apply_live_guard_to_payload({**_today_payload(), 'mode': 'action_plan'})

            today_top = str((today.get('top_pick') or {}).get('ticker') or '').upper()
            action_top = str((action.get('top_pick') or {}).get('ticker') or '').upper()

            if today_top == 'AVANTIFEED':
                return _fail('/full today must not keep AVANTIFEED as top candidate')
            if action_top == 'AVANTIFEED':
                return _fail('/full action plan must not keep AVANTIFEED as top candidate')
            if today_top != action_top:
                return _fail(f'today/action plan must agree on top pick: {today_top} vs {action_top}')

            note_snapshot_pick('today', today_top or None)
            note_snapshot_pick('action_plan', action_top or None)
            note_snapshot_pick('morning', today_top or None)
            if snapshot_consistency_warnings():
                return _fail('unified snapshot should not warn when today picks agree after live guard')
        finally:
            end_unified_snapshot()

    print('FULL_SNAPSHOT_NO_CONFLICTING_TODAY_CANDIDATE_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
