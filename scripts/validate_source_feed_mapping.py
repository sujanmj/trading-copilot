#!/usr/bin/env python3
"""
Validate Stage 44Q source-feed mapping — aliases, cached files, no fake data.

Prints exactly SOURCE_FEED_MAPPING_OK on success.
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

API_SERVER = PROJECT_ROOT / 'backend' / 'api' / 'api_server.py'
VIEWER = PROJECT_ROOT / 'backend' / 'analytics' / 'source_feed_viewer.py'


def _fail(msg: str) -> int:
    print(f'SOURCE_FEED_MAPPING_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    if not VIEWER.is_file():
        return _fail('source_feed_viewer.py missing')
    if not API_SERVER.is_file():
        return _fail('api_server.py missing')

    viewer_src = VIEWER.read_text(encoding='utf-8')
    api_src = API_SERVER.read_text(encoding='utf-8')

    if '/api/debug/source-feed' not in api_src:
        return _fail('api route /api/debug/source-feed missing')

    for token in (
        'news_feed.json',
        'live_news_feed.json',
        'external_evidence_latest.json',
        'broker_app_collector_latest.json',
        'tv_intelligence.json',
        'broker_prediction_inbox.json',
    ):
        if token not in viewer_src:
            return _fail(f'cached file not referenced: {token}')

    if 'Never invents articles' not in viewer_src and 'never invents' not in viewer_src.lower():
        return _fail('source feed viewer must document no fake news policy')

    for needle in (
        'economic times (markets)',
        'economic times markets alt',
        'economic times markets',
        'ndtv profit',
        'livemint',
        'moneycontrol',
    ):
        if needle not in viewer_src:
            return _fail(f'mapping needle missing: {needle!r}')

    try:
        from backend.analytics import source_feed_viewer as mod
    except Exception as exc:
        return _fail(f'import failed: {exc}')

    for raw, expected in (
        ('ET', 'ET'),
        ('Economic Times (Markets)', 'ET'),
        ('Economic Times Markets Alt', 'ET'),
        ('MC', 'MC'),
        ('Moneycontrol', 'MC'),
        ('Mint', 'Mint'),
        ('LiveMint (Companies)', 'Mint'),
        ('NDTV', 'NDTV'),
        ('NDTV Profit', 'NDTV'),
        ('CNBC-TV18', 'CNBC'),
        ('ET Now', 'ET Now'),
        ('Angel One', 'Angel'),
        ('Zerodha', 'Zerodha'),
        ('IndMoney', 'IndMoney'),
        ('IND Money', 'IndMoney'),
    ):
        got = mod.normalize_source_name(raw)
        if got != expected:
            return _fail(f'normalize_source_name({raw!r}) -> {got!r}, expected {expected!r}')

    et = mod.get_source_feed('ET', limit=5)
    if not isinstance(et, dict) or et.get('ok') is not True:
        return _fail(f'get_source_feed(ET) failed: {et.get("error") if isinstance(et, dict) else et}')
    if not (et.get('items') or []):
        return _fail('ET must return cached items when Economic Times data exists')

    ndtv = mod.get_source_feed('NDTV', limit=5)
    if not isinstance(ndtv, dict) or ndtv.get('ok') is not True:
        return _fail(f'get_source_feed(NDTV) failed: {ndtv.get("error") if isinstance(ndtv, dict) else ndtv}')
    if not (ndtv.get('items') or []):
        return _fail('NDTV must return cached items when NDTV Profit data exists')

    zerodha = mod.get_source_feed('Zerodha', limit=5)
    if not isinstance(zerodha, dict) or zerodha.get('ok') is not True:
        return _fail('broker source must return ok=true even when empty')

    viewer_text = VIEWER.read_text(encoding='utf-8')
    if 'write' in viewer_text.lower() and 'broker_db' in viewer_text.lower():
        return _fail('source feed viewer must not write broker DB')

    print('SOURCE_FEED_MAPPING_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
