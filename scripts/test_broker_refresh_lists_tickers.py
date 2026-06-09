#!/usr/bin/env python3
"""Unit tests for broker refresh listing tickers (Stage 48N)."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _fail(msg: str) -> int:
    print(f'BROKER_REFRESH_LISTS_TICKERS_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.analytics.broker_intelligence import format_broker_refresh_telegram

    text = format_broker_refresh_telegram({
        'ok': True,
        'cache_verify': {'ok': True, 'evidence_count': 1, 'ticker_count': 1},
        'consensus_by_ticker': {},
        'tracked_ticker_names': ['BHARTIARTL'],
        'broker_rated_tickers': 0,
        'market_mention_count': 1,
        'evidence_items': [{}],
    })
    if 'Tickers: BHARTIARTL' not in text:
        return _fail('refresh must list ticker names')
    if 'Broker-rated tickers: 0' not in text:
        return _fail('refresh must show broker-rated count')

    print('BROKER_REFRESH_LISTS_TICKERS_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
