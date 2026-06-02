#!/usr/bin/env python3
"""
Validate Stage 44AL — AI Hub per-tab lazy loading + tab refresh buttons.

Prints exactly AIHUB_PER_TAB_REFRESH_OK on success.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INDEX = PROJECT_ROOT / 'frontend' / 'index.html'

MARKER = 'GUI_BUILD_STAGE_44AL_AIHUB_PER_TAB_REFRESH'
TAB_KEYS = (
    'brain', 'govt', 'scanner', 'markets', 'global',
    'news', 'tv', 'reddit', 'stats', 'history',
)
BRAND_FALLBACK_CSS = (
    'position: absolute !important',
    'width: 1px !important',
    'clip: rect(0, 0, 0, 0) !important',
)


def _fail(msg: str) -> int:
    print(f'AIHUB_PER_TAB_REFRESH_FAIL: {msg}', file=sys.stderr)
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
    if not INDEX.is_file():
        return _fail('frontend/index.html missing')

    src = INDEX.read_text(encoding='utf-8')

    if MARKER not in src:
        return _fail(f'{MARKER} marker missing')

    if 'const AIHUB_TAB_CONFIG' not in src and 'AIHUB_TAB_API_MAP' not in src:
        return _fail('AIHUB_TAB_CONFIG or AIHUB_TAB_API_MAP missing')
    if 'async function loadAihubTabData' not in src:
        return _fail('loadAihubTabData missing')
    if 'ASTRA_GUI.aihubTabCache' not in src:
        return _fail('aihubTabCache state missing')
    if 'ASTRA_GUI.aihubTabPromises' not in src:
        return _fail('aihubTabPromises state missing')
    if 'ASTRA_GUI.aihubActiveTab' not in src:
        return _fail('aihubActiveTab state missing')

    cfg_section = _section(src, 'const AIHUB_TAB_API_MAP', 'const AIHUB_TAB_CONFIG')
    if not cfg_section:
        cfg_section = _section(src, 'const AIHUB_TAB_CONFIG', 'async function astraFetchJson')
    for key in TAB_KEYS:
        if f'{key}:' not in cfg_section and f'{key} :' not in cfg_section:
            return _fail(f'AIHUB tab map missing tab {key!r}')
    if 'ttlMs: 120000' not in src and 'AIHUB_TAB_TTL_MS = 120000' not in src:
        return _fail('AI Hub tabs must use ttlMs 120000')

    loader = _section(src, 'async function loadAihubTabData', 'function aihubTabHasCache')
    if '/api/debug/aihub-tab/' not in loader:
        return _fail('loadAihubTabData must call /api/debug/aihub-tab/')
    if 'astraFetchJson' not in loader:
        return _fail('loadAihubTabData must call astraFetchJson')
    if 'loadAihubTabDataLegacyBatch' not in src:
        return _fail('emergency legacy batch loader missing')

    if 'class="aihub-tab-refresh"' not in src and "class='aihub-tab-refresh'" not in src:
        return _fail('Refresh Tab button markup missing')
    if 'data-aihub-refresh-tab' not in src:
        return _fail('data-aihub-refresh-tab attribute missing')

    refresh_fn = _section(src, 'async function refreshAihubTabOnly', 'async function refreshAllAihubTabs')
    if 'loadAihubTabData(tabId, true)' not in refresh_fn:
        return _fail('tab refresh must call loadAihubTabData with force=true')

    activate_fn = _section(src, 'async function activateAihubTab', 'async function refreshAihubTabOnly')
    if 'loadAihubTabData(tabId, false)' not in activate_fn:
        return _fail('tab switch must call loadAihubTabData with force=false')

    if 'Using tab cache' not in src:
        return _fail('Using tab cache badge missing')
    if 'No Reddit cache yet' not in src:
        return _fail('Reddit empty state missing')
    if 'Use Refresh Tab or open Reddit source.' not in src:
        return _fail('Reddit empty-state hint must mention Refresh Tab')

    subscriber = _section(src, 'RuntimeManager.subscribe((_snap, meta)', 'try { RuntimeManager.start(30000) }')
    if 'renderAllTabs({' in subscriber or 'renderAllTabs({ force: true })' in subscriber:
        return _fail('runtime subscriber must not call renderAllTabs for every update')
    if 'renderAihubTabOnly' not in subscriber:
        return _fail('runtime subscriber must use renderAihubTabOnly')

    if 'function renderActiveAihubTab' not in src:
        return _fail('renderActiveAihubTab missing')

    tab_wire = _section(src, "document.querySelectorAll('.tab')", "safeBind('predDetailClose'")
    if 'activateAihubTab' not in tab_wire:
        return _fail('tab click must call activateAihubTab')

    header = _section(src, 'class="header-grid"', 'class="header-body-boundary"')
    if not header:
        return _fail('header-grid section missing')
    if 'astraedge-logo-img' not in src and 'astraedge-logo-wide.png' not in src:
        return _fail('logo markup missing')

    brand_css = _section(src, '.brand-fallback {', '}')
    if brand_css:
        for token in BRAND_FALLBACK_CSS:
            if token not in brand_css:
                return _fail(f'.brand-fallback missing rule: {token!r}')

    print('AIHUB_PER_TAB_REFRESH_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
