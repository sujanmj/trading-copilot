#!/usr/bin/env python3
"""
Validate Stage 44AH — AI Hub tab report/cache fallbacks in frontend/index.html.

Prints exactly AIHUB_TAB_FALLBACKS_OK on success.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INDEX = PROJECT_ROOT / 'frontend' / 'index.html'

BRAND_FALLBACK_CSS = (
    'position: absolute !important',
    'width: 1px !important',
    'clip: rect(0, 0, 0, 0) !important',
)
FALLBACK_BADGE = 'Using report/cache fallback data'
MARKER = 'GUI_BUILD_STAGE_44AH_AI_TAB_FALLBACK_FIXED'


def _fail(msg: str) -> int:
    print(f'AIHUB_TAB_FALLBACKS_FAIL: {msg}', file=sys.stderr)
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

    if 'async function loadAihubFallbackData' not in src:
        return _fail('loadAihubFallbackData must exist')

    if 'async function ensureAihubFallbackLoaded' not in src:
        return _fail('ensureAihubFallbackLoaded must exist')

    if 'Promise.allSettled' not in src:
        return _fail('loadAihubFallbackData must use Promise.allSettled')

    for endpoint in (
        '/api/debug/daily-report-pack',
        '/api/debug/external-source-coverage',
        '/api/debug/confidence-calibration',
        '/api/debug/market-memory/dashboard',
        '/api/runtime/snapshot',
    ):
        if endpoint not in src:
            return _fail(f'missing endpoint {endpoint!r}')

    if 'source-feed?source=${encodeURIComponent(src)}' not in src and "source-feed?source=" not in src:
        return _fail('source-feed fetch wiring missing')

    loader = _section(src, 'async function loadAihubFallbackData', 'function aihubFallbackBadgeHtml')
    for feed in ("'ET'", "'Reddit'"):
        if feed not in loader:
            return _fail(f'source-feed key {feed} missing from loadAihubFallbackData')

    if 'ASTRA_GUI.aihubFallback' not in src:
        return _fail('ASTRA_GUI.aihubFallback hydration missing')

    if FALLBACK_BADGE not in src:
        return _fail(f'fallback badge text missing: {FALLBACK_BADGE!r}')

    for fn in (
        'renderAihubFallbackNewsPanel',
        'renderAihubFallbackRedditPanel',
        'renderAihubFallbackTvPanel',
        'renderAihubFallbackCalibSection',
        'renderAihubFallbackJournalPanel',
        'renderAihubFallbackScannerPanel',
        'renderAihubFallbackMarketsPanel',
        'renderAihubFallbackGovtPanel',
    ):
        if f'function {fn}' not in src:
            return _fail(f'{fn} missing')

    if 'No Reddit cache yet' not in src:
        return _fail('Reddit empty-state fallback message missing')

    if 'Live sample is low — showing historical/report calibration.' not in src:
        return _fail('Calib low-live-sample message missing')

    load_news = _section(src, 'function loadNews()', 'function normalizeTvData')
    if 'aihubCollectNewsFallbackItems' not in load_news:
        return _fail('loadNews must use aihubCollectNewsFallbackItems fallback')
    if 'runtimeNewsEmpty' not in load_news:
        return _fail('loadNews must use runtimeNewsEmpty')

    load_scanner = _section(src, 'function loadScanner()', 'function loadMarkets')
    if 'renderAihubFallbackScannerPanel' not in load_scanner:
        return _fail('loadScanner must use scanner fallback renderer')
    if 'runtimeScannerEmpty' not in load_scanner:
        return _fail('loadScanner must use runtimeScannerEmpty')

    load_markets = _section(src, 'function loadMarkets()', 'function loadGlobal')
    if 'renderAihubFallbackMarketsPanel' not in load_markets:
        return _fail('loadMarkets must use markets fallback renderer')

    load_hist = _section(src, 'function loadHistory()', 'function showPredictionDetail')
    if 'renderAihubFallbackJournalPanel' not in load_hist:
        return _fail('loadHistory must use daily-report-pack journal fallback')

    if 'await ensureAihubFallbackLoaded' not in src:
        return _fail('renderAllTabs must await ensureAihubFallbackLoaded')

    header = _section(src, 'class="header-grid"', 'class="header-body-boundary"')
    if not header:
        return _fail('header-grid section missing')

    if 'astraedge-logo-wide.png' not in src and 'astraedge-logo-img' not in src:
        return _fail('logo markup missing')

    brand_css = _section(src, '.brand-fallback {', '}')
    if not brand_css:
        return _fail('.brand-fallback CSS missing')
    for token in BRAND_FALLBACK_CSS:
        if token not in brand_css:
            return _fail(f'.brand-fallback missing accessible hidden rule: {token!r}')

    if re.search(r'<div class="topbar">', src):
        return _fail('header redesign detected — legacy topbar must not return')

    print('AIHUB_TAB_FALLBACKS_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
