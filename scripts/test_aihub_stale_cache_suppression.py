#!/usr/bin/env python3
"""Stage 50P — stale Brain/Govt/Market AI Hub cache suppressed in /aihub full."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

STALE_AGE_SEC = 325 * 3600
SCARY_BRAIN = 'CRITICAL MARKET CRASH IMMINENT — SELL EVERYTHING NOW'


def _fail(msg: str) -> int:
    print(f'AIHUB_STALE_CACHE_SUPPRESSION_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.telegram.response_format import format_aihub_full, format_aihub_payload

    stale_brain = {
        'source': 'cache',
        'cache_age_seconds': STALE_AGE_SEC,
        'summary': {'stale': True},
        'items': [{'title': SCARY_BRAIN, 'summary': SCARY_BRAIN}],
        'warnings': [],
    }
    tab_text = format_aihub_payload('brain', stale_brain)
    if 'Brain cache stale — run /refresh full' not in tab_text:
        return _fail(f'brain tab must show stale warning, got: {tab_text!r}')
    if SCARY_BRAIN in tab_text:
        return _fail('stale brain tab must suppress old scary summary content')

    full = format_aihub_full({
        'brain': stale_brain,
        'govt': {
            'cache_age_seconds': STALE_AGE_SEC,
            'summary': {'stale': True},
            'items': [{'title': 'Old govt policy shock headline from 325h ago'}],
        },
        'market': {
            'cache_age_seconds': STALE_AGE_SEC,
            'summary': {'market_stale': True, 'market_mode': 'INDIA_OPEN'},
            'items': [],
        },
        'scan': {'summary': {}, 'items': [], 'live_scanner': []},
        'global': {'summary': {}, 'items': []},
        'news': {'items': []},
        'tv': {'items': []},
        'calib': {'summary': {}},
        'journal': {'summary': {}, 'items': []},
    })
    if 'Brain cache stale — run /refresh full' not in full:
        return _fail('/aihub full must show brain stale warning')
    if SCARY_BRAIN in full:
        return _fail('/aihub full must not include stale 325h brain summary')
    if 'Govt cache stale — run /refresh full' not in full:
        return _fail('/aihub full must show govt stale warning')
    if 'Market cache stale — run /refresh full' not in full:
        return _fail('/aihub full must show market stale warning')
    if 'Old govt policy shock headline from 325h ago' in full:
        return _fail('/aihub full must suppress stale govt headline body')

    print('AIHUB_STALE_CACHE_SUPPRESSION_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
