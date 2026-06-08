#!/usr/bin/env python3
"""Unit tests for cache-first AI Hub tab GET (Stage 48C)."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _fail(msg: str) -> int:
    print(f'AIHUB_CACHE_FIRST_TABS_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    api_src = (PROJECT_ROOT / 'backend/api/api_server.py').read_text(encoding='utf-8')
    idx = (PROJECT_ROOT / 'frontend/index.html').read_text(encoding='utf-8')
    payloads_src = (PROJECT_ROOT / 'backend/analytics/aihub_tab_payloads.py').read_text(encoding='utf-8')

    get_block = api_src.split('def api_debug_aihub_tab(')[1].split('def api_debug_aihub_tab_refresh')[0]
    if 'cache_only=True' not in get_block:
        return _fail('GET aihub-tab must use cache_only=True')
    if '/api/debug/aihub-tab/{tab}/refresh' not in api_src:
        return _fail('POST refresh route missing')
    if 'refresh=1&_ts=' in idx and '/refresh`, { method: \'POST\' }' not in idx:
        return _fail('frontend must not auto GET refresh=1 without POST refresh path')
    if '/refresh`, { method: \'POST\' }' not in idx:
        return _fail('frontend refresh must use POST /refresh')
    if 'emergency legacy batch' in idx:
        return _fail('frontend must not emergency legacy batch on tab load')
    if 'def build_aihub_tab_payload' not in payloads_src or 'cache_only' not in payloads_src:
        return _fail('build_aihub_tab_payload missing cache_only')

    from backend.analytics.aihub_tab_payloads import build_aihub_tab_payload

    with patch('backend.analytics.aihub_tab_payloads.load_aihub_tab_cache', return_value=None):
        with patch('backend.analytics.aihub_tab_payloads.build_brain_payload') as brain_mock:
            payload = build_aihub_tab_payload('brain', cache_only=True)
            if not brain_mock.called:
                pass
            else:
                return _fail('cache_only must not call brain builder when cache missing')
            if not payload.get('cache_missing'):
                return _fail('expected cache_missing placeholder')

    print('AIHUB_CACHE_FIRST_TABS_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
