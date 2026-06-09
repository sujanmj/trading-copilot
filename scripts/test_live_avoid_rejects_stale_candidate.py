#!/usr/bin/env python3
"""Unit tests — live avoid registry rejects stale AVANTIFEED top pick (Stage 48Q)."""

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
    print(f'LIVE_AVOID_REJECTS_STALE_CANDIDATE_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.analytics.unified_decision_engine import (
        LIVE_REJECTION_MSG,
        apply_live_guard_to_payload,
    )

    registry = {'AVANTIFEED': 'STRONG BEARISH — breakdown on weak participation'}
    payload = {
        'ok': True,
        'mode': 'today',
        'ranked_candidates': [
            {
                'ticker': 'AVANTIFEED',
                'action': 'BUY_CANDIDATE',
                'score': 88,
                'risk': [],
                'why': ['Stale overnight report'],
                'supports': [],
            },
            {
                'ticker': 'RELIANCE',
                'action': 'BUY_CANDIDATE',
                'score': 74,
                'risk': [],
                'why': ['Live scanner alignment'],
                'supports': ['scanner'],
            },
        ],
        'top_pick': {
            'ticker': 'AVANTIFEED',
            'action': 'BUY_CANDIDATE',
            'score': 88,
        },
        'decision': 'BUY_CANDIDATE',
    }

    with patch(
        'backend.analytics.unified_decision_engine.load_live_avoid_registry',
        return_value=registry,
    ), patch(
        'backend.analytics.unified_decision_engine.get_feed_freshness_meta',
        return_value={
            'report_stale': True,
            'scanner_fresh': True,
            'report_age_min': 660,
            'scanner_age_min': 2,
        },
    ):
        guarded = apply_live_guard_to_payload(payload)

    top = guarded.get('top_pick') or {}
    if str(top.get('ticker') or '').upper() == 'AVANTIFEED':
        return _fail('AVANTIFEED in avoid registry cannot remain top_pick')
    if str(top.get('ticker') or '').upper() != 'RELIANCE':
        return _fail(f'expected RELIANCE fallback top_pick got {top!r}')

    avant_row = next(
        (r for r in guarded.get('ranked_candidates') or [] if r.get('ticker') == 'AVANTIFEED'),
        None,
    )
    if not avant_row or avant_row.get('action') != 'AVOID':
        return _fail('AVANTIFEED must be marked AVOID after live guard')
    if LIVE_REJECTION_MSG not in ' '.join(avant_row.get('risk') or []):
        return _fail('AVANTIFEED rejection must cite live scanner / bearish confirmation')

    print('LIVE_AVOID_REJECTS_STALE_CANDIDATE_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
