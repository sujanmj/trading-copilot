#!/usr/bin/env python3
"""Unit tests for old budget cache direction backfill (Stage 48H)."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.analytics import budget_impact as bi


def _fail(msg: str) -> int:
    print(f'BUDGET_OLD_CACHE_DIRECTION_BACKFILL_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    old_cache = {
        'ok': True,
        'generated_at': '2026-06-08T10:00:00+05:30',
        'top_catalysts': [
            {
                'theme_id': 'cement_steel_paint',
                'headline': 'Tata Steel UK project delayed by regulatory review',
                'catalyst_score': 55,
            },
        ],
        'themes_by_id': {
            'roads_highways': {
                'theme_id': 'roads_highways',
                'display_name': 'Roads & Highways',
                'catalysts': [
                    {
                        'theme_id': 'roads_highways',
                        'headline': 'Govt announces highway project in Bengaluru',
                        'catalyst_score': 60,
                    },
                ],
            },
        },
        'catalysts_by_theme': {
            'roads_highways': [
                {
                    'theme_id': 'roads_highways',
                    'headline': 'Govt announces highway project in Bengaluru',
                    'catalyst_score': 60,
                },
            ],
        },
        'catalysts_by_id': {},
        'drilldown_by_catalyst': {'legacy_stub': {'ok': True}},
    }

    with tempfile.TemporaryDirectory() as tmp:
        cache_path = Path(tmp) / 'budget_impact_cache.json'
        cache_path.write_text(json.dumps(old_cache), encoding='utf-8')
        orig_cache = bi.CACHE_FILE
        bi.CACHE_FILE = cache_path
        try:
            cached = bi.ensure_cache_indexes(bi._load_cache())
            overview = bi.get_budget_overview(cache_only=True, lite=True)
            news = bi.get_budget_theme_news('roads_highways', cache_only=True, lite=True)
            detail = bi.get_budget_theme_detail('roads_highways', cache_only=True, lite=True)
        finally:
            bi.CACHE_FILE = orig_cache

    for cat in overview.get('top_catalysts') or []:
        if cat.get('catalyst_direction') != 'Negative':
            return _fail(f'top catalyst backfill expected Negative: {cat!r}')

    for cat in news.get('catalysts') or []:
        if cat.get('catalyst_direction') != 'Positive':
            return _fail(f'theme news backfill expected Positive: {cat!r}')

    detail_cats = (detail.get('catalysts') or []) + ((detail.get('theme') or {}).get('catalysts') or [])
    for cat in detail_cats:
        direction = cat.get('catalyst_direction')
        if not direction or direction == '?':
            return _fail(f'theme detail missing direction: {cat!r}')

    if not cached.get('catalysts_by_id'):
        return _fail('ensure_cache_indexes should populate catalysts_by_id')

    print('BUDGET_OLD_CACHE_DIRECTION_BACKFILL_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
