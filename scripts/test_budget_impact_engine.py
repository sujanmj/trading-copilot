#!/usr/bin/env python3
"""Unit tests for Budget Impact Intelligence engine (Stage 48A)."""

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
    print(f'BUDGET_IMPACT_ENGINE_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    import backend.analytics.budget_impact as bi
    import backend.analytics.theme_baskets as tb

    with tempfile.TemporaryDirectory() as tmp:
        baskets_path = Path(tmp) / 'theme_baskets.json'
        log_path = Path(tmp) / 'theme_catalyst_log.jsonl'
        cache_path = Path(tmp) / 'budget_impact_cache.json'
        event_path = Path(tmp) / 'budget_event_log.jsonl'
        orig_baskets = tb.BASKETS_FILE
        orig_log = tb.CATALYST_LOG_FILE
        orig_cache = bi.CACHE_FILE
        orig_event = bi.EVENT_LOG_FILE
        tb.BASKETS_FILE = baskets_path
        tb.CATALYST_LOG_FILE = log_path
        bi.CACHE_FILE = cache_path
        bi.EVENT_LOG_FILE = event_path
        try:
            tb.bootstrap_theme_baskets(force=True)

            overview = bi.get_budget_overview()
            if not overview.get('ok'):
                return _fail('overview not ok')
            if not overview.get('top_themes'):
                return _fail('overview missing top_themes')
            if overview.get('stage') != '48A':
                return _fail('overview stage not 48A')

            themes = bi.get_budget_themes()
            if not themes.get('categories') or themes.get('count', 0) < 30:
                return _fail('themes grouped list too small')

            highway = bi.analyze_news_text(
                'Govt announces ₹11,000 crore highway project in Bengaluru'
            )
            detected_ids = [t.get('theme_id') for t in (highway.get('detected_themes') or [])]
            for expected in ('roads_highways', 'infrastructure', 'cement_steel_paint'):
                if expected not in detected_ids:
                    return _fail(f'highway news missing theme {expected}')

            pos = highway.get('positive') or []
            ind = highway.get('indirect') or []
            if pos and ind and pos[0].get('score', 0) < ind[0].get('score', 0):
                return _fail('direct beneficiaries should rank above indirect')

            crude = bi.analyze_news_text('Crude spike hits Brent — aviation and paints under margin risk')
            crude_ids = [t.get('theme_id') for t in (crude.get('detected_themes') or [])]
            if 'crude_sensitive' not in crude_ids and 'oil_gas_energy' not in crude_ids:
                return _fail('crude spike missing crude/oil themes')

            rbi = bi.analyze_news_text('RBI repo rate hike — NBFC and real estate rate sensitive')
            rbi_ids = [t.get('theme_id') for t in (rbi.get('detected_themes') or [])]
            if 'rbi_rates' not in rbi_ids:
                return _fail('rate hike missing rbi_rates theme')

            defence = bi.analyze_news_text('Union budget defence allocation for make in india orders')
            def_ids = [t.get('theme_id') for t in (defence.get('detected_themes') or [])]
            if 'defence_aerospace' not in def_ids:
                return _fail('defence allocation missing defence_aerospace')

            rail = bi.analyze_news_text('Railway allocation capex for metro and rolling stock')
            rail_ids = [t.get('theme_id') for t in (rail.get('detected_themes') or [])]
            if 'railways_metro' not in rail_ids:
                return _fail('railway allocation missing railways_metro')

            political = bi.analyze_news_text(
                'Congress govt may lose Karnataka and BJP may come to power'
            )
            if not political.get('political_neutral'):
                return _fail('political text should use neutral policy mode')
            if 'party' in str(political.get('summary', '')).lower():
                return _fail('political summary should avoid party bias wording')

            stale_panel = bi.compute_freshness_panel()
            stale_panel['status'] = 'stale'
            stance = bi._stance_for_score(80, stale=True)
            if stance != 'Research Only':
                return _fail('stale data should produce Research Only stance')

            refresh = bi.refresh_budget_intel(persist=True)
            if not refresh.get('ok'):
                return _fail('refresh failed')
            if not cache_path.is_file():
                return _fail('budget_impact_cache.json not written')
        finally:
            tb.BASKETS_FILE = orig_baskets
            tb.CATALYST_LOG_FILE = orig_log
            bi.CACHE_FILE = orig_cache
            bi.EVENT_LOG_FILE = orig_event

    print('BUDGET_IMPACT_ENGINE_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
