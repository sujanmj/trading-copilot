#!/usr/bin/env python3
"""Unit tests for Budget API routes (Stage 48A)."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)


def _fail(msg: str) -> int:
    print(f'BUDGET_API_ROUTES_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    import backend.analytics.budget_impact as bi
    import backend.analytics.theme_baskets as tb

    api_src = (PROJECT_ROOT / 'backend/api/api_server.py').read_text(encoding='utf-8')
    for route in (
        '/api/budget/overview',
        '/api/budget/themes',
        '/api/budget/theme/{theme_id}',
        '/api/budget/news/{theme_id}',
        '/api/budget/scan/{theme_id}',
        '/api/budget/analyze-news',
        '/api/budget/refresh',
    ):
        if route not in api_src:
            return _fail(f'missing route {route}')

    if "'stage': '48A'" not in api_src:
        return _fail('build-info stage not 48A')

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
            if not overview.get('ok') or not overview.get('top_themes'):
                return _fail('overview route logic failed')

            themes = bi.get_budget_themes()
            if not themes.get('categories'):
                return _fail('themes route logic failed')

            detail = bi.get_budget_theme_detail('infra')
            if not detail.get('ok') or detail.get('theme_id') != 'infrastructure':
                return _fail('theme detail should resolve infra alias')

            news = bi.get_budget_theme_news('infrastructure')
            if not news.get('ok') or not isinstance(news.get('catalysts'), list):
                return _fail('news route should return catalysts list')

            scan = bi.get_budget_theme_scan('infrastructure')
            stocks = scan.get('stocks') or []
            if not scan.get('ok') or not stocks:
                return _fail('scan route should return ranked stocks')
            if 'stance' not in stocks[0]:
                return _fail('scan stocks missing stance column')

            analyze = bi.analyze_news_text('Govt announces new highway project in Bengaluru', persist=True)
            if not analyze.get('ok'):
                return _fail('analyze-news failed')

            missing = bi.get_budget_theme_detail('not_a_real_theme_xyz')
            if missing.get('ok'):
                return _fail('unknown theme should not be ok')

            refresh = bi.refresh_budget_intel(persist=True)
            if not refresh.get('ok'):
                return _fail('refresh route failed')

            json.dumps({'overview': overview, 'themes': themes, 'scan': scan, 'analyze': analyze})
        finally:
            tb.BASKETS_FILE = orig_baskets
            tb.CATALYST_LOG_FILE = orig_log
            bi.CACHE_FILE = orig_cache
            bi.EVENT_LOG_FILE = orig_event

    print('BUDGET_API_ROUTES_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
