#!/usr/bin/env python3
"""Stage 50L — avoid/rejected tickers must not appear in watch displays."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _fail(msg: str) -> int:
    print(f'OBSERVATION_NO_WATCH_AVOID_CONTRADICTION_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.analytics.premarket_conviction import _apply_conflict_guard
    from backend.analytics.unified_decision_engine import (
        filter_rows_exclude_avoid,
        filter_ticker_list_exclude_avoid,
    )
    from backend.telegram.response_format import format_watchlist_with_rejections

    registry = {'EASEMYTRIP': 'Avoid list', 'RELIANCE': 'Bearish breakdown'}
    setups = [
        {'ticker': 'EASEMYTRIP', 'setup': 'Gap up', 'score': 70},
        {'ticker': 'IXIGO', 'setup': 'Momentum', 'score': 65},
    ]
    avoids = [{'ticker': 'EASEMYTRIP', 'reason': 'weak participation'}]
    guarded = _apply_conflict_guard(setups, avoids)
    tickers = [s['ticker'] for s in guarded]
    if 'EASEMYTRIP' in tickers:
        return _fail('EASEMYTRIP must be excluded from setups after conflict guard')

    filtered_rows = filter_rows_exclude_avoid(setups, registry)
    if any(r.get('ticker') == 'EASEMYTRIP' for r in filtered_rows):
        return _fail('filter_rows_exclude_avoid must drop EASEMYTRIP')

    clean = filter_ticker_list_exclude_avoid(['EASEMYTRIP', 'IXIGO', 'RELIANCE'], registry)
    if 'EASEMYTRIP' in clean or 'RELIANCE' in clean:
        return _fail('filter_ticker_list_exclude_avoid must drop avoid tickers')
    if 'IXIGO' not in clean:
        return _fail('IXIGO should remain in clean watch list')

    split = format_watchlist_with_rejections(['EASEMYTRIP', 'IXIGO'], registry)
    if 'EASEMYTRIP' in split['clean']:
        return _fail('EASEMYTRIP cannot appear in clean watchlist')

    print('OBSERVATION_NO_WATCH_AVOID_CONTRADICTION_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
