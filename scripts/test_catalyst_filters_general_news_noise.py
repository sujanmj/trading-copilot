#!/usr/bin/env python3
"""Stage 50O — generic neutral news filtered from top list."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _fail(msg: str) -> int:
    print(f'CATALYST_FILTERS_GENERAL_NEWS_NOISE_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.intelligence.stock_catalyst_radar import build_catalyst_radar, _now_iso

    ts = _now_iso()
    fake = [
        {
            'ticker': 'NIFTY',
            'headline': 'Markets open flat amid global cues',
            'catalyst_type': 'GENERAL_NEWS',
            'side': 'NEUTRAL',
            'source_key': 'news_feed',
            'published_at': ts,
        },
        {
            'ticker': 'HCLTECH',
            'headline': 'HCL Tech shares jump 3% after buying stake in Sarvam AI',
            'catalyst_type': 'AI_INVESTMENT',
            'side': 'BULLISH',
            'source_key': 'news_feed',
            'published_at': ts,
        },
    ]

    def _quote(ticker: str):
        if ticker == 'HCLTECH':
            return {'ticker': 'HCLTECH', 'price': 1600, 'change_percent': 3.0, 'volume_ratio': 1.2}
        return {}

    with patch('backend.intelligence.stock_catalyst_radar._collect_raw_catalysts', return_value=fake), \
         patch('backend.intelligence.stock_catalyst_radar._scanner_quote', side_effect=_quote), \
         patch('backend.intelligence.stock_catalyst_radar.CACHE_FILE', PROJECT_ROOT / 'data' / '_test_catalyst_noise.json'):
        radar = build_catalyst_radar(persist=False, force_refresh=True)

    priority = radar.get('priority_list') or []
    if any(r.get('catalyst_type') == 'GENERAL_NEWS' and r.get('side') == 'NEUTRAL' for r in priority):
        return _fail('generic neutral news must not appear in top priority list')
    if not any(r.get('ticker') == 'HCLTECH' for r in priority):
        return _fail('named catalyst stock should remain in priority list')

    print('CATALYST_FILTERS_GENERAL_NEWS_NOISE_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
