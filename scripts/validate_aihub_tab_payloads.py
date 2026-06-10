#!/usr/bin/env python3
"""
Validate Stage 44AQ — AI Hub single tab payload endpoint + frontend wiring.

Prints exactly AIHUB_TAB_PAYLOADS_OK on success.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INDEX = PROJECT_ROOT / 'frontend' / 'index.html'
PAYLOADS = PROJECT_ROOT / 'backend' / 'analytics' / 'aihub_tab_payloads.py'
API_SERVER = PROJECT_ROOT / 'backend' / 'api' / 'api_server.py'

MARKER = 'GUI_BUILD_STAGE_44AQ_AIHUB_TAB_PAYLOADS'
API_TABS = (
    'brain', 'govt', 'scan', 'market', 'global', 'news', 'tv', 'calib', 'journal',
)
FRONTEND_TAB_KEYS = (
    'brain', 'govt', 'scanner', 'markets', 'global', 'news', 'tv', 'stats', 'history',
)


def _fail(msg: str) -> int:
    print(f'AIHUB_TAB_PAYLOADS_FAIL: {msg}', file=sys.stderr)
    return 1


def _section(src: str, start_marker: str, end_marker: str) -> str:
    start = src.find(start_marker)
    if start < 0:
        return ''
    end = src.find(end_marker, start)
    if end < 0:
        return src[start:]
    return src[start:end]


def main() -> int:
    if not PAYLOADS.is_file():
        return _fail('backend/analytics/aihub_tab_payloads.py missing')

    payloads_src = PAYLOADS.read_text(encoding='utf-8')
    for fn in (
        'build_aihub_tab_payload',
        'build_brain_payload',
        'build_govt_payload',
        'build_scan_payload',
        'build_market_payload',
        'build_global_payload',
        'build_news_payload',
        'build_tv_payload',
        'build_calib_payload',
        'build_journal_payload',
    ):
        if f'def {fn}' not in payloads_src:
            return _fail(f'{fn} missing')

    if 'is_memory_fallback' not in payloads_src or 'market-memory' not in payloads_src:
        return _fail('scan memory fallback markers missing in backend payloads')

    if 'SOURCE_TIMEOUT_SEC = 3.0' not in payloads_src:
        return _fail('SOURCE_TIMEOUT_SEC must be 3.0')

    if not API_SERVER.is_file():
        return _fail('backend/api/api_server.py missing')

    api_src = API_SERVER.read_text(encoding='utf-8')
    if '/api/debug/aihub-tab/{tab}' not in api_src:
        return _fail('/api/debug/aihub-tab/{tab} route missing')
    if 'build_aihub_tab_payload' not in api_src:
        return _fail('api route must call build_aihub_tab_payload')

    if not INDEX.is_file():
        return _fail('frontend/index.html missing')

    src = INDEX.read_text(encoding='utf-8')
    if MARKER not in src:
        return _fail(f'{MARKER} marker missing')

    if 'AIHUB_TAB_API_MAP' not in src:
        return _fail('AIHUB_TAB_API_MAP missing')

    loader = _section(src, 'async function loadAihubTabData', 'function aihubTabHasCache')
    if '/api/debug/aihub-tab/' not in loader:
        return _fail('loadAihubTabData must call /api/debug/aihub-tab/')
    if 'loadAihubTabDataLegacyBatch' not in src:
        return _fail('emergency legacy batch loader missing')
    if 'cfg.endpoints.map' in loader:
        return _fail('loadAihubTabData must not use multi-endpoint batch for normal render')

    if 'ttlMs: 120000' not in src and 'AIHUB_TAB_TTL_MS = 120000' not in src:
        return _fail('2 minute tab cache TTL missing')

    if 'buildFallbackFromAihubPayload' not in src:
        return _fail('buildFallbackFromAihubPayload missing')

    scan_helpers = _section(src, 'function isMemoryFallbackScanRow', 'function hasValidLiveScanPrice')
    if 'is_memory_fallback' not in scan_helpers:
        return _fail('isMemoryFallbackScanRow must check is_memory_fallback')

    if 'formatScanRowDisplay' not in _section(src, 'function loadScanner()', 'function loadMarkets'):
        return _fail('loadScanner must use formatScanRowDisplay for live rows')

    if 'No Reddit cache yet' not in src:
        return _fail('Reddit empty state copy missing')

    header = _section(src, 'class="header-grid"', 'class="header-body-boundary"')
    if not header:
        return _fail('header-grid section missing')
    if 'astraedge-logo-img' not in src and 'astraedge-logo-wide.png' not in src:
        return _fail('logo markup missing')

    for tab in API_TABS:
        if f"'{tab}'" not in payloads_src and f'"{tab}"' not in payloads_src:
            if tab not in payloads_src:
                return _fail(f'backend tab {tab!r} not supported')

    cfg_section = _section(src, 'const AIHUB_TAB_API_MAP', 'const AIHUB_TAB_CONFIG')
    for key in FRONTEND_TAB_KEYS:
        if f'{key}:' not in cfg_section:
            return _fail(f'AIHUB_TAB_API_MAP missing frontend tab {key!r}')

    print('AIHUB_TAB_PAYLOADS_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
