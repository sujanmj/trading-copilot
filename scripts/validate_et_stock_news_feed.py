#!/usr/bin/env python3
"""
Validate ET source feed includes stock-related cached classifications (Stage 44G).

Prints exactly ET_STOCK_NEWS_FEED_OK on success.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if str(Path.cwd().resolve()) != str(PROJECT_ROOT.resolve()):
    os.chdir(PROJECT_ROOT)

STOCK_CLASSIFICATIONS = {
    'stock_news',
    'stock_news_evidence',
    'broker_candidates',
    'broker_prediction_candidate',
    'market_context',
    'macro_context',
}


def _fail(msg: str) -> int:
    print(f'ET_STOCK_NEWS_FEED_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    try:
        from backend.analytics.source_feed_viewer import get_source_feed
    except Exception as exc:
        return _fail(f'import failed: {exc}')

    payload = get_source_feed('ET', limit=100)
    if payload.get('ok') is not True:
        return _fail(f"ET feed not ok: {payload.get('error')}")

    items = payload.get('items') or []
    if not items:
        return _fail('ET feed has no cached items')

    counts = payload.get('counts') or {}
    stock_related = (
        int(counts.get('stock_news') or 0)
        + int(counts.get('broker_candidates') or 0)
        + int(counts.get('market_context') or 0)
        + int(counts.get('macro_context') or 0)
    )
    if stock_related < 1:
        class_set = {str(i.get('classification') or '') for i in items}
        if not (class_set & STOCK_CLASSIFICATIONS):
            return _fail('ET feed lacks stock/market/macro/broker classifications')

    et_sources = {str(i.get('source') or '').lower() for i in items}
    if not any('economic times' in s or 'et ' in s for s in et_sources):
        return _fail('ET items must come from Economic Times cached sources')

    has_title = any((i.get('title') or '').strip() for i in items)
    if not has_title:
        return _fail('ET items must include titles from cache')

    print('ET_STOCK_NEWS_FEED_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
