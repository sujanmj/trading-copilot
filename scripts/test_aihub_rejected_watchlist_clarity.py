#!/usr/bin/env python3
"""Unit tests — AIHub journal splits rejected tickers (Stage 48T)."""

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
    print(f'AIHUB_REJECTED_WATCHLIST_CLARITY_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.telegram.response_format import format_aihub_full, strip_stage_markers

    journal_payload = {
        'market_mode': 'INDIA_AFTER_HOURS',
        'summary': {
            'market_mode': 'INDIA_AFTER_HOURS',
            'top_watch': [
                {'ticker': 'RELIANCE'},
                {'ticker': 'AMBER'},
                {'ticker': 'AVANTIFEED'},
            ],
            'failed_strong_warnings': [],
        },
        'items': [
            {'ticker': 'RELIANCE'},
            {'ticker': 'AMBER'},
            {'ticker': 'AVANTIFEED'},
        ],
    }

    with patch(
        'backend.analytics.unified_decision_engine.build_live_rejection_set',
        return_value={'AVANTIFEED': 'STRONG BEARISH breakdown'},
    ):
        text = strip_stage_markers(format_aihub_full({'calib': {'summary': {}}, 'journal': journal_payload}))

    if 'top watchlist: RELIANCE, AMBER, AVANTIFEED' in text:
        return _fail('rejected ticker must not appear in plain top watchlist')
    if '• RELIANCE' not in text or '• AMBER' not in text:
        return _fail('clean journal items missing from full summary')
    if 'rejected today:' not in text.lower() and 'Rejected today:' not in text:
        return _fail('journal must label rejected today ticker separately')

    print('AIHUB_REJECTED_WATCHLIST_CLARITY_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
