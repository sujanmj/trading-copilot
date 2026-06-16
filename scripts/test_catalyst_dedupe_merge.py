#!/usr/bin/env python3
"""Stage 50O — catalyst radar merges duplicate tickers."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _fail(msg: str) -> int:
    print(f'CATALYST_DEDUPE_MERGE_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.intelligence.stock_catalyst_radar import build_catalyst_radar, _merge_raw_by_ticker

    raw = [
        {'ticker': 'GICRE', 'headline': 'GICRE OFS opens', 'catalyst_type': 'OFS', 'side': 'BEARISH', 'source_key': 'news_feed'},
        {'ticker': 'GICRE', 'headline': 'GICRE stake sale via OFS', 'catalyst_type': 'OFS', 'side': 'BEARISH', 'source_key': 'news_feed'},
    ]
    merged = _merge_raw_by_ticker(raw)
    if len(merged) != 1:
        return _fail(f'expected 1 merged row got {len(merged)}')
    if merged[0].get('ticker') != 'GICRE':
        return _fail('merged ticker must be GICRE')
    notes = merged[0].get('catalyst_notes') or []
    if len(notes) < 2:
        return _fail('merged row must keep all catalyst notes')

    fake_collect = [
        {
            'ticker': 'GICRE',
            'headline': 'GICRE OFS opens',
            'catalyst_type': 'OFS',
            'side': 'BEARISH',
            'source_key': 'news_feed',
            'published_at': '2026-06-16T09:00:00+05:30',
        },
        {
            'ticker': 'GICRE',
            'headline': 'GICRE stake sale via OFS',
            'catalyst_type': 'OFS',
            'side': 'BEARISH',
            'source_key': 'news_feed',
            'published_at': '2026-06-16T08:00:00+05:30',
        },
    ]
    with patch('backend.intelligence.stock_catalyst_radar._collect_raw_catalysts', return_value=fake_collect), \
         patch('backend.intelligence.stock_catalyst_radar._scanner_quote', return_value={}), \
         patch('backend.intelligence.stock_catalyst_radar.CACHE_FILE', PROJECT_ROOT / 'data' / '_test_catalyst_dedupe.json'):
        radar = build_catalyst_radar(persist=False, force_refresh=True)
    gicre_items = [r for r in radar.get('items') or [] if r.get('ticker') == 'GICRE']
    if len(gicre_items) != 1:
        return _fail(f'build_catalyst_radar must merge to one GICRE row got {len(gicre_items)}')
    gicre_rows = [r for r in radar.get('priority_list') or [] if r.get('ticker') == 'GICRE']
    if len(gicre_rows) > 1:
        return _fail('/catalysts priority list must have at most one GICRE row')

    print('CATALYST_DEDUPE_MERGE_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
