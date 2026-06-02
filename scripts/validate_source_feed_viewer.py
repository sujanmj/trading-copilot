#!/usr/bin/env python3
"""
Validate backend source_feed_viewer module (Stage 44G).

Prints exactly SOURCE_FEED_VIEWER_OK on success.
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


def _fail(msg: str) -> int:
    print(f'SOURCE_FEED_VIEWER_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    try:
        from backend.analytics import source_feed_viewer as mod
    except Exception as exc:
        return _fail(f'import failed: {exc}')

    for fn_name in ('normalize_source_name', 'group_cached_news_by_source', 'get_source_feed'):
        if not callable(getattr(mod, fn_name, None)):
            return _fail(f'missing function: {fn_name}')

    if mod.normalize_source_name('et') != 'ET':
        return _fail('normalize_source_name(et) must map to ET')
    if mod.normalize_source_name('MC') != 'MC':
        return _fail('normalize_source_name(MC) must stay MC')

    grouped = mod.group_cached_news_by_source()
    if not isinstance(grouped, dict):
        return _fail('group_cached_news_by_source must return dict')

    payload = mod.get_source_feed('ET', limit=50)
    if not isinstance(payload, dict):
        return _fail('get_source_feed must return dict')
    for key in ('ok', 'source', 'source_label', 'items', 'counts', 'last_updated'):
        if key not in payload:
            return _fail(f'get_source_feed missing key: {key}')
    if payload.get('ok') is not True:
        return _fail(f"get_source_feed ET ok != true: {payload.get('error')}")
    if payload.get('source') != 'ET':
        return _fail('ET feed source key mismatch')

    counts = payload.get('counts') or {}
    for ck in ('total', 'stock_news', 'market_context', 'macro_context', 'broker_candidates'):
        if ck not in counts:
            return _fail(f'counts missing {ck}')

    items = payload.get('items') or []
    if items:
        row = items[0]
        for fk in ('title', 'classification', 'ticker', 'direction', 'published_at', 'url', 'source'):
            if fk not in row:
                return _fail(f'item missing field: {fk}')

    print('SOURCE_FEED_VIEWER_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
