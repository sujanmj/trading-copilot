#!/usr/bin/env python3
"""Unit tests for generic watchlist filter (Stage 48O)."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _fail(msg: str) -> int:
    print(f'BROKER_GENERIC_WATCHLIST_FILTER_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.analytics.broker_intelligence import build_broker_intelligence_cache, classify_evidence_type

    headlines = (
        'Key stocks in focus today',
        'Top gainers and losers in trade today',
        'Buzzing stocks: Tata Motors, Infosys',
    )
    for headline in headlines:
        et = classify_evidence_type({'headline': headline}, text=headline)
        if et != 'market_watchlist_mention':
            return _fail(f'{headline!r} should be market_watchlist_mention, got {et!r}')

    broker = classify_evidence_type(
        {'headline': 'Motilal Oswal maintains buy rating on Infosys with target price hike'},
        text='Motilal Oswal maintains buy rating on Infosys with target price hike',
    )
    if broker == 'market_watchlist_mention':
        return _fail('true broker headline must not be watchlist mention')

    print('BROKER_GENERIC_WATCHLIST_FILTER_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
