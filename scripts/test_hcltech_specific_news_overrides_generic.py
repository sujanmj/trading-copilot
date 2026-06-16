#!/usr/bin/env python3
"""Stage 50P — HCLTECH specific Sarvam AI headline beats generic Sensex noise."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

GENERIC = 'Sensex rises over 250 points; HCL Tech among top gainers'
SPECIFIC = 'HCL Tech shares jump 3% after buying stake in Sarvam AI for Rs 1,427 crore'


def _fail(msg: str) -> int:
    print(f'HCLTECH_SPECIFIC_NEWS_OVERRIDES_GENERIC_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.intelligence.stock_catalyst_radar import _merge_raw_by_ticker, score_catalyst_row

    merged = _merge_raw_by_ticker([
        {'ticker': 'HCLTECH', 'headline': GENERIC, 'catalyst_type': 'GENERAL_NEWS', 'side': 'NEUTRAL',
         'published_at': '2026-06-16T10:00:00+05:30', 'source_key': 'news_feed'},
        {'ticker': 'HCLTECH', 'headline': SPECIFIC, 'catalyst_type': 'GENERAL_NEWS', 'side': 'NEUTRAL',
         'published_at': '2026-06-16T09:30:00+05:30', 'source_key': 'news_feed'},
    ])
    if len(merged) != 1:
        return _fail(f'expected one HCLTECH row got {len(merged)}')
    row = merged[0]
    if row.get('side') != 'BULLISH':
        return _fail(f"expected BULLISH side got {row.get('side')!r}")
    if row.get('catalyst_type') not in ('AI_INVESTMENT', 'STAKE_BUY', 'ACQUISITION'):
        return _fail(f"expected AI/stake catalyst got {row.get('catalyst_type')!r}")
    if row.get('side') == 'MIXED':
        return _fail('generic Sensex headline must not downgrade specific news to MIXED')

    scored = score_catalyst_row({**row, 'quote_available': True, 'change_pct': 3.0, 'volume_ratio': 1.1})
    if scored.get('side') == 'MIXED':
        return _fail('scored row must stay BULLISH after merge')
    if scored.get('priority') == 'LOW' and scored.get('side') == 'BULLISH':
        return _fail('specific AI catalyst must not become LOW priority')

    print('HCLTECH_SPECIFIC_NEWS_OVERRIDES_GENERIC_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
