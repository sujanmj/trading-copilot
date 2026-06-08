#!/usr/bin/env python3
"""Unit tests for theme basket API routes (Stage 47A)."""

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
    print(f'THEME_API_ROUTES_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def _api_list():
    from backend.analytics.theme_baskets import list_all_baskets, load_theme_baskets

    data = load_theme_baskets()
    return {
        'ok': True,
        'stage': data.get('stage', '47E'),
        'generated_at': data.get('generated_at'),
        'cache_refreshed_at': data.get('cache_refreshed_at'),
        'baskets': list_all_baskets(),
        'count': len(list_all_baskets()),
    }


def _api_detail(theme_id: str):
    from backend.analytics.theme_baskets import get_basket_by_id, resolve_theme_id

    resolved = resolve_theme_id(theme_id)
    basket = get_basket_by_id(theme_id)
    if not basket:
        return None
    return {'ok': True, 'theme_id': resolved, 'basket': basket}


def _api_news(theme_id: str):
    from backend.analytics.theme_baskets import get_basket_by_id, get_theme_catalysts, resolve_theme_id

    if not get_basket_by_id(theme_id):
        return None
    catalysts = get_theme_catalysts(theme_id, limit=12)
    return {
        'ok': True,
        'theme_id': resolve_theme_id(theme_id),
        'catalysts': catalysts,
        'count': len(catalysts),
    }


def _api_scan(theme_id: str):
    from backend.analytics.theme_baskets import get_basket_by_id, rank_theme_stocks, resolve_theme_id

    if not get_basket_by_id(theme_id):
        return None
    ranked = rank_theme_stocks(theme_id, limit=12)
    return {
        'ok': True,
        'theme_id': resolve_theme_id(theme_id),
        'stocks': ranked,
        'count': len(ranked),
    }


def main() -> int:
    import backend.analytics.theme_baskets as tb

    api_src = (PROJECT_ROOT / 'backend/api/api_server.py').read_text(encoding='utf-8')
    for route in (
        'api_theme_baskets_list',
        'api_theme_basket_detail',
        'api_theme_basket_news',
        'api_theme_basket_scan',
        'api_theme_basket_add',
        'api_theme_basket_remove',
        'api_theme_baskets_refresh',
    ):
        if f'def {route}' not in api_src:
            return _fail(f'api_server missing handler {route}')

    with tempfile.TemporaryDirectory() as tmp:
        baskets_path = Path(tmp) / 'theme_baskets.json'
        log_path = Path(tmp) / 'theme_catalyst_log.jsonl'
        orig_baskets = tb.BASKETS_FILE
        orig_log = tb.CATALYST_LOG_FILE
        tb.BASKETS_FILE = baskets_path
        tb.CATALYST_LOG_FILE = log_path
        try:
            tb.bootstrap_theme_baskets(force=True)

            listing = _api_list()
            if not isinstance(listing, dict) or not listing.get('ok'):
                return _fail('list route should return ok JSON')
            if listing.get('count', 0) < 40:
                return _fail(f'list route expected >=40 baskets, got {listing.get("count")}')

            detail = _api_detail('infra')
            if not detail or detail.get('theme_id') != 'infrastructure':
                return _fail('detail route should resolve infra alias')
            basket = detail.get('basket') or {}
            if basket.get('theme_id') != 'infrastructure':
                return _fail('detail route basket mismatch')

            news = _api_news('infrastructure')
            if not news or not isinstance(news.get('catalysts'), list):
                return _fail('news route should return catalysts list')

            scan = _api_scan('infrastructure')
            if not scan:
                return _fail('scan route failed')
            stocks = scan.get('stocks') or []
            if not stocks:
                return _fail('scan route should return ranked stocks')
            if stocks[0].get('score', 0) < stocks[-1].get('score', 0):
                return _fail('scan stocks should be sorted by score desc')

            add_result = tb.add_stock_to_basket('infra', 'TESTME', 'direct')
            if not add_result.get('ok'):
                return _fail('add route failed')

            remove_result = tb.remove_stock_from_basket('infra', 'TESTME')
            if not remove_result.get('ok'):
                return _fail('remove route failed')

            refresh = tb.refresh_theme_catalyst_cache(persist=True)
            if not refresh.get('ok'):
                return _fail('refresh route failed')

            json.dumps({
                'listing': listing,
                'detail': detail,
                'news': news,
                'scan': scan,
                'refresh': refresh,
            })
        finally:
            tb.BASKETS_FILE = orig_baskets
            tb.CATALYST_LOG_FILE = orig_log

    print('THEME_API_ROUTES_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
