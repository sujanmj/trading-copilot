#!/usr/bin/env python3
"""Unit tests for get_top_broker_display_candidates backward compatibility (48L hotfix)."""

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
    print(f'BROKER_DISPLAY_CANDIDATES_COMPAT_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    lazy_src = (PROJECT_ROOT / 'backend/telegram/lazy_command_runner.py').read_text(encoding='utf-8')
    broker_src = (
        PROJECT_ROOT / 'backend/analytics/broker_prediction_intelligence.py'
    ).read_text(encoding='utf-8')
    if 'def get_top_broker_display_candidates' not in broker_src:
        return _fail('broker_prediction_intelligence missing get_top_broker_display_candidates')
    if 'get_top_broker_display_candidates' not in lazy_src:
        return _fail('lazy_command_runner missing get_top_broker_display_candidates wiring')

    from backend.analytics.broker_prediction_intelligence import get_top_broker_display_candidates

    missing_cache = {
        'ok': True,
        'cache_missing': True,
        'tracked_tickers': 0,
        'top_positive': [],
        'top_negative': [],
        'evidence_items': [],
    }
    with patch(
        'backend.analytics.broker_intelligence.get_broker_intel_overview',
        return_value=missing_cache,
    ):
        empty = get_top_broker_display_candidates(limit=5)
    if not empty.get('ok'):
        return _fail('missing cache must return ok payload')
    if empty.get('candidates') not in ([], None) and empty.get('candidates'):
        pass
    if empty.get('candidates'):
        return _fail('missing cache must return empty candidates')
    if empty.get('pick_count') not in (0, None):
        return _fail('missing cache must return zero pick_count')

    rich_cache = {
        'ok': True,
        'cache_missing': False,
        'tracked_tickers': 2,
        'top_positive': [{
            'ticker': 'RELIANCE',
            'consensus_label': 'Positive',
            'confidence_score': 72,
            'freshness': 'fresh',
            'evidence': [{
                'broker_house': 'Research Desk',
                'headline': 'Reliance target raised',
                'source': 'Research Desk',
            }],
        }],
        'top_negative': [{
            'ticker': 'TATASTEEL',
            'consensus_label': 'Negative',
            'confidence_score': 28,
            'freshness': 'stale',
            'evidence': [{
                'broker_house': 'External',
                'headline': 'Tata Steel downgrade on delay',
            }],
        }],
        'evidence_items': [],
    }
    with patch(
        'backend.analytics.broker_intelligence.get_broker_intel_overview',
        return_value=rich_cache,
    ):
        display = get_top_broker_display_candidates(limit=5)

    candidates = display.get('candidates') or []
    if len(candidates) < 2:
        return _fail('expected mapped candidates from intel cache')
    first = candidates[0]
    for key in ('ticker', 'direction', 'source'):
        if key not in first:
            return _fail(f'candidate missing {key}')
    if first.get('direction') not in {'BULLISH', 'BEARISH', 'NEUTRAL', 'MIXED'}:
        return _fail(f'unexpected direction {first.get("direction")!r}')
    if '?' in str(first.get('direction')):
        return _fail('direction must not contain ?')

    from backend.telegram.lazy_command_runner import run_broker_only

    with patch('backend.analytics.broker_intelligence.handle_broker_command', return_value='Broker overview'):
        with patch(
            'backend.analytics.broker_prediction_intelligence.get_top_broker_display_candidates',
            return_value=display,
        ):
            result = run_broker_only(refresh=False)
    stats = (result.get('payload') or {}).get('stats') or {}
    if int(stats.get('picks_tracked') or 0) < 1:
        return _fail('run_broker_only payload must expose picks_tracked from display candidates')

    print('BROKER_DISPLAY_CANDIDATES_COMPAT_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
