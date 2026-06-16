#!/usr/bin/env python3
"""Stage 50Q — HCLTECH Sarvam AI stake headlines forced BULLISH / AI_INVESTMENT."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

HEADLINES = (
    'HCL Tech shares jump 3% after buying stake in Sarvam AI for Rs 1,427 crore',
    'HCL Technologies announces buying stake in Sarvam AI',
    'Company completes Sarvam AI stake purchase',
)


def _fail(msg: str) -> int:
    print(f'HCLTECH_AI_INVESTMENT_FORCED_BULLISH_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.intelligence.stock_catalyst_radar import _merge_raw_by_ticker, classify_catalyst

    for headline in HEADLINES:
        ctype, side = classify_catalyst(headline)
        if side != 'BULLISH':
            return _fail(f'classify_catalyst must force BULLISH for {headline!r} got {side!r}')
        if ctype not in ('AI_INVESTMENT', 'STAKE_BUY'):
            return _fail(f'expected AI_INVESTMENT/STAKE_BUY for {headline!r} got {ctype!r}')

    generic = 'Sensex rises over 250 points; HCL Tech among top gainers'
    specific = 'HCL Tech shares jump 3% after buying stake in Sarvam AI for Rs 1,427 crore'
    merged = _merge_raw_by_ticker([
        {'ticker': 'HCLTECH', 'headline': generic, 'published_at': '2026-06-16T10:00:00+05:30'},
        {'ticker': 'HCLTECH', 'headline': specific, 'published_at': '2026-06-16T09:30:00+05:30'},
    ])
    if len(merged) != 1:
        return _fail(f'expected one merged row got {len(merged)}')
    row = merged[0]
    if row.get('side') != 'BULLISH':
        return _fail(f'merged side must stay BULLISH got {row.get("side")!r}')
    if row.get('catalyst_type') not in ('AI_INVESTMENT', 'STAKE_BUY'):
        return _fail(f'merged catalyst_type must be AI/stake got {row.get("catalyst_type")!r}')
    if row.get('side') == 'MIXED':
        return _fail('generic Sensex headline must not downgrade to MIXED')

    print('HCLTECH_AI_INVESTMENT_FORCED_BULLISH_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
