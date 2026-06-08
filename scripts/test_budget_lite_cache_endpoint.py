#!/usr/bin/env python3
"""Unit tests for budget lite cache endpoints (Stage 48D)."""

from __future__ import annotations

import sys
import time
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _fail(msg: str) -> int:
    print(f'BUDGET_LITE_CACHE_ENDPOINT_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    api_src = (PROJECT_ROOT / 'backend/api/api_server.py').read_text(encoding='utf-8')
    bi_src = (PROJECT_ROOT / 'backend/analytics/budget_impact.py').read_text(encoding='utf-8')

    if 'lite: int = Query(0)' not in api_src.split('api_budget_overview')[1][:400]:
        return _fail('overview missing lite query param')
    if 'get_budget_overview(cache_only=bool(cache_only), lite=bool(lite))' not in api_src:
        return _fail('overview must pass lite flag')
    if 'def get_budget_overview(*, cache_only: bool = False, lite: bool = False)' not in bi_src:
        return _fail('get_budget_overview missing lite param')

    from backend.analytics import budget_impact as bi

    with patch('backend.analytics.budget_impact._load_cache', return_value={}):
        with patch('backend.analytics.budget_impact.compute_freshness_panel') as fresh_mock:
            with patch('backend.analytics.theme_baskets.refresh_theme_catalyst_cache') as refresh_mock:
                start = time.perf_counter()
                payload = bi.get_budget_overview(cache_only=True, lite=True)
                elapsed = time.perf_counter() - start
                if fresh_mock.called:
                    return _fail('lite overview must not call compute_freshness_panel')
                if refresh_mock.called:
                    return _fail('lite overview must not call refresh_theme_catalyst_cache')
                if not payload.get('cache_missing'):
                    return _fail('empty cache must return cache_missing')
                if elapsed > 2.0:
                    return _fail('lite overview too slow')

    with patch('backend.analytics.theme_baskets.get_theme_catalysts') as cat_mock:
        themes = bi.get_budget_themes(lite=True)
        if cat_mock.called:
            return _fail('lite themes must not call get_theme_catalysts')
        if not themes.get('ok') or not themes.get('categories'):
            return _fail('lite themes must return grouped categories')

    print('BUDGET_LITE_CACHE_ENDPOINT_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
