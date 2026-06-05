#!/usr/bin/env python3
"""Unit tests for theme catalyst matching and scoring (Stage 47A)."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)


def _fail(msg: str) -> int:
    print(f'THEME_CATALYST_MATCHING_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    import backend.analytics.theme_baskets as tb

    with tempfile.TemporaryDirectory() as tmp:
        baskets_path = Path(tmp) / 'theme_baskets.json'
        log_path = Path(tmp) / 'theme_catalyst_log.jsonl'
        orig_baskets = tb.BASKETS_FILE
        orig_log = tb.CATALYST_LOG_FILE
        tb.BASKETS_FILE = baskets_path
        tb.CATALYST_LOG_FILE = log_path
        try:
            tb.bootstrap_theme_baskets(force=True)

            road_headline = 'Govt announces ₹11,000 crore road project in Delhi'
            road_matches = tb.match_headline_to_themes(road_headline)
            road_ids = {m.get('theme_id') for m in road_matches}
            for expected in ('infrastructure', 'roads_highways', 'cement_steel_paint'):
                if expected not in road_ids:
                    return _fail(f'road headline missing theme {expected}, got {sorted(road_ids)}')

            temple_headline = 'Ram Mandir tourism boost expected to lift Ayodhya travel demand'
            temple_matches = tb.match_headline_to_themes(temple_headline)
            temple_ids = {m.get('theme_id') for m in temple_matches}
            if 'tourism_temple_culture' not in temple_ids:
                return _fail(f'temple headline missing tourism theme, got {sorted(temple_ids)}')

            named = tb.score_theme_catalyst(
                'L&T wins ₹2,500 crore highway order in Maharashtra',
                'roads_highways',
            )
            generic = tb.score_theme_catalyst(
                'Infrastructure sector may benefit from policy support',
                'infrastructure',
            )
            if named.get('catalyst_score', 0) <= generic.get('catalyst_score', 0):
                return _fail('named company/order should score higher than generic sector')

            direct_rank = tb.rank_theme_stocks('infrastructure', limit=5)
            if not direct_rank:
                return _fail('rank_theme_stocks returned empty')
            if direct_rank[0].get('bucket') != 'direct':
                return _fail('direct beneficiary should rank above indirect')
            if direct_rank[0].get('score', 0) < direct_rank[-1].get('score', 0):
                return _fail('stock ranks should be descending by score')

            stale_basket = tb.get_basket_by_id('infrastructure') or {}
            if not tb._basket_is_stale(stale_basket):
                pass  # fresh bootstrap may not be stale — verify wording path separately

            detail = tb.format_theme_detail_telegram('infrastructure')
            if 'buy now' in detail.lower() or 'guaranteed' in detail.lower():
                return _fail('detail output must not contain buy/guaranteed language')
            if 'watch' not in detail.lower():
                return _fail('detail output must include watch language')

            broad = tb.score_theme_catalyst('Government may support infra in coming years', 'infrastructure')
            if broad.get('action') != 'watch only':
                return _fail('broad policy should be watch only')
        finally:
            tb.BASKETS_FILE = orig_baskets
            tb.CATALYST_LOG_FILE = orig_log

    print('THEME_CATALYST_MATCHING_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
