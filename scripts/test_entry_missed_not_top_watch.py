#!/usr/bin/env python3
"""Stage 50Z — ENTRY_MISSED must not appear as normal Top watch."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _fail(msg: str) -> int:
    print(f'ENTRY_MISSED_NOT_TOP_WATCH_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.trading.unified_live_priority_engine import (
        PULLBACK_WATCH_ONLY,
        _select_top_pick,
        format_intraday_provisional_unified,
        format_today_unified,
    )

    payload = {
        'ok': True,
        'mode': 'today',
        'decision': 'NO_CLEAN_CANDIDATE',
        'top_pick': None,
        'all_entry_missed': True,
        'missed_candidates': [{
            'ticker': 'NOCIL',
            'action': PULLBACK_WATCH_ONLY,
            'entry_status': 'ENTRY_MISSED',
            'entry_missed': True,
            'unified_score': 72,
            'why': ['Live scanner confirmation'],
            'risk': ['Entry missed on live move'],
        }],
        'ranked_candidates': [{
            'ticker': 'NOCIL',
            'action': PULLBACK_WATCH_ONLY,
            'entry_status': 'ENTRY_MISSED',
            'entry_missed': True,
            'unified_score': 72,
        }],
    }

    today_text = format_today_unified(payload)
    intraday_text = format_intraday_provisional_unified(payload)

    for label, text in (('today', today_text), ('intraday', intraday_text)):
        if 'NOCIL' not in text:
            return _fail(f'{label} must mention NOCIL as missed context')
        if 'WATCH FOR ENTRY' in text.upper():
            return _fail(f'{label} must not promote ENTRY_MISSED as WATCH FOR ENTRY')
        if 'No clean top watch yet' not in text:
            return _fail(f'{label} must say no clean top watch when only missed names exist')
        if 'wait for pullback/reset' not in text.lower():
            return _fail(f'{label} must instruct pullback/reset wait')

    ranked = [
        {
            'ticker': 'NOCIL',
            'action': PULLBACK_WATCH_ONLY,
            'entry_status': 'ENTRY_MISSED',
            'entry_missed': True,
            'unified_score': 72,
        },
        {
            'ticker': 'RELIANCE',
            'action': 'WATCH_FOR_ENTRY',
            'entry_status': 'VALID_ENTRY',
            'entry_missed': False,
            'unified_score': 60,
        },
    ]
    top, decision = _select_top_pick(ranked)
    if not top or top.get('ticker') != 'RELIANCE':
        return _fail('top_pick must skip ENTRY_MISSED and choose clean watch name')

    print('ENTRY_MISSED_NOT_TOP_WATCH_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
