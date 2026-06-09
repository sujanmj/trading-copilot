#!/usr/bin/env python3
"""Unit tests — /aihub journal tab excludes rejected tickers (Stage 48U)."""

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
    print(f'AIHUB_JOURNAL_REJECTED_TICKER_REMOVED_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.telegram.response_format import format_aihub_payload, strip_stage_markers

    payload = {
        'source': 'cache',
        'cache_age_seconds': 30,
        'summary': {'history': {'count': 0}},
        'items': [
            {'ticker': 'RELIANCE'},
            {'ticker': 'AMBER'},
            {'ticker': 'BAJAJELEC'},
            {'ticker': 'COCHINSHIP'},
            {'ticker': 'GSPL'},
            {'ticker': 'AVANTIFEED'},
        ],
    }

    with patch(
        'backend.analytics.unified_decision_engine.build_live_rejection_set',
        return_value={'AVANTIFEED': 'STRONG BEARISH breakdown'},
    ):
        text = strip_stage_markers(format_aihub_payload('journal', payload))

    if '• AVANTIFEED' in text and 'Rejected today:' not in text:
        return _fail('rejected ticker listed as normal journal item')
    if 'Rejected today:' not in text:
        return _fail('journal must include Rejected today section')
    if '• AVANTIFEED — live scanner rejection' not in text:
        return _fail('journal rejected line missing live scanner rejection detail')
    if '• RELIANCE' not in text or '• AMBER' not in text:
        return _fail('clean journal items missing')

    print('AIHUB_JOURNAL_REJECTED_TICKER_REMOVED_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
