#!/usr/bin/env python3
"""Unit tests for budget catalyst direction (Stage 48F)."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.analytics.budget_impact import detect_catalyst_direction, rank_stocks_for_catalyst


def _fail(msg: str) -> int:
    print(f'BUDGET_CATALYST_DIRECTION_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    delay = 'Tata Steel UK project delayed by regulatory review'
    highway = 'Govt announces ₹11,000 crore highway project in Bengaluru'

    if detect_catalyst_direction(delay) != 'Negative':
        return _fail('Tata Steel delay must be Negative')
    if detect_catalyst_direction(highway) != 'Positive':
        return _fail('Highway Bengaluru project must be Positive')

    delay_rank = rank_stocks_for_catalyst(delay, 'cement_steel_paint')
    pos_tickers = {r['ticker'] for r in delay_rank['sections']['positive_investment_watch']}
    if pos_tickers:
        return _fail('Negative catalyst must not create positive investment watch rows')

    avoid = delay_rank['sections']['avoid_risk']
    if not any(r['ticker'] == 'TATASTEEL' for r in avoid):
        return _fail('TATASTEEL must be Avoid/Risk on delay headline')

    hi_rank = rank_stocks_for_catalyst(highway, 'roads_highways')
    direct = {r['ticker'] for r in hi_rank['sections']['positive_investment_watch']}
    for ticker in ('HGINFRA', 'IRB', 'PNCINFRA'):
        if ticker not in direct:
            return _fail(f'{ticker} must be direct beneficiary for highway catalyst')

    print('BUDGET_CATALYST_DIRECTION_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
