#!/usr/bin/env python3
"""Unit tests — /today after-hours research wording (Stage 48S)."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

BANNER = 'Market closed/after-hours — treat as research watchlist.'


def _fail(msg: str) -> int:
    print(f'AFTER_HOURS_TODAY_WORDING_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.telegram.response_format import format_stock_decision_payload, strip_stage_markers

    payload = {
        'ok': True,
        'decision': 'WATCH_FOR_ENTRY',
        'top_pick': {
            'ticker': 'RELIANCE',
            'action': 'WATCH_FOR_ENTRY',
            'score': 72,
            'confidence': 'medium',
            'why': ['test'],
        },
        'telegram_message': '<b>AstraEdge — Today</b>\nTop candidate: RELIANCE — WATCH FOR ENTRY',
    }

    with patch('backend.telegram.india_mode_lock.is_after_hours_phase', return_value=True):
        text = strip_stage_markers(format_stock_decision_payload(payload, 'today'))

    if BANNER not in text:
        return _fail('/today missing after-hours research banner')
    if text.count(BANNER) != 1:
        return _fail('after-hours banner must appear once')

    print('AFTER_HOURS_TODAY_WORDING_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
