#!/usr/bin/env python3
"""Unit tests for premarket freshness and quality (Stage 46I)."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)


def _fail(msg: str) -> int:
    print(f'PREMARKET_FRESHNESS_QUALITY_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.analytics.premarket_conviction import (
        _apply_conflict_guard,
        _apply_volume_caps,
        _format_global_sentiment_dict,
        _negative_move_label,
        format_premarket_telegram,
    )
    from backend.orchestration.alert_freshness_gate import (
        PREMARKET_INCOMPLETE_HEADER,
        PREMARKET_SCORE_CAP,
        cap_premarket_scores,
        premarket_freshness_state,
    )

    with patch('backend.orchestration.alert_freshness_gate.check_core_freshness', return_value=(False, 'stale', ['scanner'])):
        ok, header, keys = premarket_freshness_state()
    if ok:
        return _fail('stale premarket should not be ok')
    if PREMARKET_INCOMPLETE_HEADER not in header:
        return _fail('missing incomplete header')
    if 'scanner' not in keys:
        return _fail('expected stale scanner key')

    capped = cap_premarket_scores([{'ticker': 'X', 'score': 95}], cap=PREMARKET_SCORE_CAP)
    if capped[0]['score'] > 65:
        return _fail('freshness cap should be <=65')

    report = {
        'market_bias': 'Bullish',
        'top_setups': [{'ticker': 'ABC', 'score': 95, 'setup': 'WATCH', 'reasons': ['test']}],
        'avoid': [],
        'market_mode': {'market_mode': 'INDIA_PREMARKET_MODE'},
        'freshness_ok': False,
        'freshness_header': PREMARKET_INCOMPLETE_HEADER,
        'sector_cues': {},
        'overnight_global': {
            'sentiment': {'usa': {'mood': 'BEARISH', 'average_change': -0.51}},
            'sentiment_formatted': 'US: Bearish (-0.51%)',
        },
    }
    text = format_premarket_telegram(full=True, report=report, slot='premarket_top3')
    if PREMARKET_INCOMPLETE_HEADER not in text:
        return _fail('telegram missing freshness header')
    if 'watchlist preparation only' not in text.lower():
        return _fail('missing watchlist preparation only note')
    if '{' in text and "'usa'" in text:
        return _fail('raw sentiment dict in telegram')

    formatted = _format_global_sentiment_dict({
        'usa': {'mood': 'BEARISH', 'average_change': -0.51},
        'asia': {'mood': 'BEARISH', 'average_change': -1.81},
        'global': {'mood': 'BEARISH', 'average_change': -0.78},
    })
    for needle in ('US: Bearish', 'Asia: Bearish', 'Global: Bearish'):
        if needle not in formatted:
            return _fail(f'missing formatted sentiment line: {needle}')

    adjusted, deferred = _apply_volume_caps(
        [{'ticker': 'LOW', 'score': 80, 'setup': 'WATCH', 'reasons': []}],
        {'top_signals': [{'ticker': 'LOW', 'volume_ratio': 0.2}]},
        {},
    )
    if not deferred:
        return _fail('vol<0.3 should defer from top watch')
    if 'ignore unless volume' not in deferred[0].get('setup', '').lower():
        return _fail('vol<0.3 wrong label')

    neg = _negative_move_label(-2.5, 'BEARISH')
    if 'bullish' in neg.lower():
        return _fail('negative move must not be bullish')

    conflicted = _apply_conflict_guard(
        [{'ticker': 'NHPC', 'score': 70, 'setup': 'WATCH', 'reasons': ['gap']}],
        [{'ticker': 'NHPC', 'reason': 'weak vol'}],
    )
    if conflicted[0].get('setup') != 'Conflict/Wait':
        return _fail('NHPC conflict guard failed')

    titles = {
        'premarket_top3': 'PREMARKET TOP SETUPS',
        'premarket_action': 'PREMARKET FULL BRIEF',
        'preopen_watch': 'PRE-OPEN WATCH',
        'live_validation': 'FIRST LIVE VALIDATION',
        'open_confirmation': 'OPEN CONFIRMATION',
    }
    for slot, marker in titles.items():
        msg = format_premarket_telegram(full=slot.endswith('action'), report={
            'market_bias': 'Neutral',
            'top_setups': [],
            'avoid': [],
            'market_mode': {'market_mode': 'INDIA_PREOPEN_MODE'},
            'freshness_ok': True,
            'sector_cues': {},
            'overnight_global': {},
        }, slot=slot)
        if marker not in msg:
            return _fail(f'slot {slot} missing title marker {marker}')

    print('PREMARKET_FRESHNESS_QUALITY_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
