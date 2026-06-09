#!/usr/bin/env python3
"""Unit tests for missing broker ticker suggestions (Stage 48N)."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _fail(msg: str) -> int:
    print(f'BROKER_MISSING_TICKER_SUGGESTIONS_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.analytics.broker_intelligence import format_broker_ticker_telegram

    cache = {
        'ok': True,
        'generated_at': '2026-05-27T10:00:00+05:30',
        'consensus_by_ticker': {'NIFTY50': {'ticker': 'NIFTY50', 'consensus_label': 'Neutral', 'confidence_score': 45}},
        'tracked_ticker_names': ['NIFTY50'],
        'evidence_items': [{'ticker': 'NIFTY50'}],
    }

    with patch('backend.analytics.broker_intelligence.get_broker_intel_ticker', return_value={
        'ok': True,
        'cache_missing': False,
        'found': False,
        'ticker': 'RELIANCE',
    }):
        with patch('backend.analytics.broker_intelligence._load_cache', return_value=cache):
            text = format_broker_ticker_telegram('RELIANCE')

    if 'No broker intelligence for RELIANCE' not in text:
        return _fail('missing not-found message')
    if 'Available tracked tickers' not in text:
        return _fail('must suggest available tracked tickers')
    if 'NIFTY50' not in text:
        return _fail('must list NIFTY50')
    if 'Use /broker NIFTY50' not in text:
        return _fail('must suggest drilldown command')

    print('BROKER_MISSING_TICKER_SUGGESTIONS_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
