#!/usr/bin/env python3
"""Unit tests for budget API routes (Stage 48G)."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.analytics import budget_impact as bi


def _fail(msg: str) -> int:
    print(f'BUDGET_API_ROUTES_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    api = (PROJECT_ROOT / 'backend/api/api_server.py').read_text(encoding='utf-8')
    routes = (
        '/api/budget/theme/{theme_id}',
        '/api/budget/news/{theme_id}',
        '/api/budget/scan/{theme_id}',
        '/api/budget/catalyst/{catalyst_id}',
        'get_budget_theme_detail(theme_id, cache_only=bool(cache_only), lite=bool(lite))',
        'get_budget_theme_news(theme_id, cache_only=bool(cache_only), lite=bool(lite))',
        'get_budget_catalyst_drilldown',
    )
    for needle in routes:
        if needle not in api:
            return _fail(f'api_server.py missing {needle!r}')

    cached = {'ok': True, 'freshness': {'status': 'partial'}, 'top_catalysts': []}
    with patch('backend.analytics.budget_impact._load_cache', return_value=cached):
        with patch('backend.analytics.theme_baskets.get_basket_by_id', return_value={'theme_id': 'roads_highways', 'display_name': 'Roads / Highways'}):
            theme = bi.get_budget_theme_detail('roads_highways', cache_only=True, lite=True)
            news = bi.get_budget_theme_news('roads_highways', cache_only=True, lite=True)
            scan = bi.get_budget_theme_scan('roads_highways', cache_only=True, lite=True)
    for payload, name in ((theme, 'theme'), (news, 'news'), (scan, 'scan')):
        if not payload.get('ok') and not payload.get('cache_missing'):
            return _fail(f'{name} lite route must return ok JSON')

    print('BUDGET_API_ROUTES_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
