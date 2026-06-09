#!/usr/bin/env python3
"""Unit tests — /aihub full scan watchlist excludes rejected tickers (Stage 48U)."""

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
    print(f'AIHUB_FULL_REJECTED_TICKER_REMOVED_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.telegram.response_format import format_aihub_full, strip_stage_markers

    scan_payload = {
        'summary': {'live_scanner_count': 30},
        'live_scanner': [
            {'ticker': 'EASEMYTRIP'},
            {'ticker': 'ANDHRSUGAR'},
            {'ticker': 'DATAPATTNS'},
        ],
        'watchlist_candidates': [
            {'ticker': 'RELIANCE'},
            {'ticker': 'AMBER'},
            {'ticker': 'AVANTIFEED'},
        ],
        'items': [],
    }

    with patch(
        'backend.analytics.unified_decision_engine.build_live_rejection_set',
        return_value={'AVANTIFEED': 'STRONG BEARISH breakdown'},
    ):
        text = strip_stage_markers(format_aihub_full({'scan': scan_payload, 'calib': {'summary': {}}, 'journal': {'summary': {}}}))

    if 'top watchlist: RELIANCE, AMBER, AVANTIFEED' in text:
        return _fail('rejected ticker must not appear in plain top watchlist')
    if 'top watchlist: RELIANCE, AMBER' not in text:
        return _fail('clean watchlist tickers missing from scan section')
    if 'rejected today: avantifeed' not in text.lower():
        return _fail('scan section must show rejected today line')

    print('AIHUB_FULL_REJECTED_TICKER_REMOVED_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
