#!/usr/bin/env python3
"""Unit tests — AVANTIFEED cannot stay top when live bearish (Stage 48R)."""

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
    print(f'AVANTIFEED_NOT_TOP_WHEN_LIVE_BEARISH_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.analytics.unified_decision_engine import (
        HARD_REJECTION_MSG,
        apply_live_guard_to_payload,
        pick_live_safe_top,
    )

    registry = {'AVANTIFEED': 'STRONG BEARISH — breakdown on weak participation'}
    ranked = [
        {
            'ticker': 'AVANTIFEED',
            'action': 'BUY_CANDIDATE',
            'score': 91,
            'risk': [],
            'why': ['Overnight report leader'],
            'supports': [],
        },
        {
            'ticker': 'TCS',
            'action': 'BUY_CANDIDATE',
            'score': 76,
            'risk': [],
            'why': ['Live scanner bullish'],
            'supports': ['scanner'],
        },
    ]
    freshness_meta = {
        'report_stale': True,
        'scanner_fresh': True,
        'report_age_min': 600,
        'scanner_age_min': 4,
    }

    top, decision, _warnings = pick_live_safe_top(ranked, registry, mode='today')
    if (top or {}).get('ticker') == 'AVANTIFEED':
        return _fail('pick_live_safe_top must not return AVANTIFEED when live bearish')
    if (top or {}).get('ticker') != 'TCS':
        return _fail(f'expected TCS fallback top got {top!r}')
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
        'backend.analytics.unified_decision_engine.build_live_rejection_set',
        return_value=registry,
    ), patch(
        'backend.analytics.unified_decision_engine.get_feed_freshness_meta',
        return_value=freshness_meta,
    ):
        guarded = apply_live_guard_to_payload(payload)

    guarded_top = str((guarded.get('top_pick') or {}).get('ticker') or '').upper()
    if guarded_top == 'AVANTIFEED':
        return _fail('AVANTIFEED must not remain top_pick after live guard')
    if guarded_top != 'TCS':
        return _fail(f'expected TCS guarded top got {guarded_top!r}')

    avant_row = next(
        (r for r in guarded.get('ranked_candidates') or [] if r.get('ticker') == 'AVANTIFEED'),
        None,
    )
    if not avant_row or avant_row.get('action') != 'AVOID':
        return _fail('AVANTIFEED must be demoted to AVOID')
    if HARD_REJECTION_MSG not in ' '.join(avant_row.get('risk') or []):
        return _fail('AVANTIFEED must cite hard live rejection in risk')

    print('AVANTIFEED_NOT_TOP_WHEN_LIVE_BEARISH_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
