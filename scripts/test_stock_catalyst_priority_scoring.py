#!/usr/bin/env python3
"""Stage 50N — catalyst priority scoring and ranking."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _fail(msg: str) -> int:
    print(f'STOCK_CATALYST_PRIORITY_SCORING_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.intelligence.stock_catalyst_radar import score_catalyst_row

    fresh = score_catalyst_row({
        'ticker': 'HCLTECH',
        'catalyst_type': 'ACQUISITION',
        'side': 'BULLISH',
        'change_pct': 3.1,
        'volume_ratio': 1.4,
        'source_key': 'news_feed',
        'published_at': '2026-06-16T08:30:00+05:30',
    })
    stale = score_catalyst_row({
        'ticker': 'RANDOM',
        'catalyst_type': 'GENERAL_NEWS',
        'side': 'NEUTRAL',
        'change_pct': 0.2,
        'volume_ratio': 0.5,
        'source_key': 'news_feed',
        'published_at': '2026-06-10T08:30:00+05:30',
    })
    bear = score_catalyst_row({
        'ticker': 'GICRE',
        'catalyst_type': 'OFS',
        'side': 'BEARISH',
        'change_pct': -6.0,
        'volume_ratio': 1.2,
        'source_key': 'news_feed',
        'published_at': '2026-06-16T08:00:00+05:30',
    })

    if float(fresh.get('score') or 0) <= float(stale.get('score') or 0):
        return _fail('fresh catalyst must outrank stale neutral')
    if fresh.get('priority') not in ('HIGH', 'MEDIUM'):
        return _fail(f'fresh bullish catalyst should be HIGH/MEDIUM got {fresh.get("priority")}')
    if bear.get('priority') != 'AVOID':
        return _fail(f'bearish OFS must be AVOID got {bear.get("priority")}')
    if 'freshness' not in (fresh.get('score_breakdown') or {}):
        return _fail('score_breakdown must include freshness')

    print('STOCK_CATALYST_PRIORITY_SCORING_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
