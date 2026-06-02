#!/usr/bin/env python3
"""
Validate Stage 44AJ — fetch storm repair (AI Hub fallback singleton + runtime snapshot dedup).

Prints exactly FETCH_STORM_REPAIR_OK on success.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INDEX = PROJECT_ROOT / 'frontend' / 'index.html'
RUNTIME = PROJECT_ROOT / 'frontend' / 'runtime' / 'runtimeManager.js'
MEMORY_CANDIDATES = (
    PROJECT_ROOT / 'frontend' / 'runtime' / 'MarketMemoryPanel.js',
    PROJECT_ROOT / 'frontend' / 'components' / 'MarketMemoryPanel.js',
)

MARKER = 'GUI_BUILD_STAGE_44AJ_FETCH_STORM_REPAIR'
BRAND_FALLBACK_CSS = (
    'position: absolute !important',
    'width: 1px !important',
    'clip: rect(0, 0, 0, 0) !important',
)


def _fail(msg: str) -> int:
    print(f'FETCH_STORM_REPAIR_FAIL: {msg}', file=sys.stderr)
    return 1


def _section(src: str, start_marker: str, end_marker: str) -> str:
    start = src.find(start_marker)
    if start < 0:
        return ''
    end = src.find(end_marker, start)
    if end < 0:
        return src[start:]
    return src[start:end]


def _memory_panel_path() -> Path | None:
    for path in MEMORY_CANDIDATES:
        if path.is_file():
            return path
    return None


def main() -> int:
    if not INDEX.is_file():
        return _fail('frontend/index.html missing')
    if not RUNTIME.is_file():
        return _fail('frontend/runtime/runtimeManager.js missing')

    memory_path = _memory_panel_path()
    if memory_path is None:
        return _fail('MarketMemoryPanel.js missing')

    index_src = INDEX.read_text(encoding='utf-8')
    runtime_src = RUNTIME.read_text(encoding='utf-8')
    memory_src = memory_path.read_text(encoding='utf-8')

    if MARKER not in index_src:
        return _fail(f'{MARKER} marker missing')

    err_fn = _section(memory_src, 'function renderErrorHtml', 'function renderLoadingHtml')
    if not err_fn:
        return _fail('renderErrorHtml not found in MarketMemoryPanel.js')
    if re.search(r'(?<!\.)\brefreshing\b', err_fn):
        return _fail('renderErrorHtml must not reference bare refreshing')
    if 'isRefreshing' not in err_fn:
        return _fail('renderErrorHtml must define isRefreshing safe fallback')

    loader = _section(index_src, 'async function loadAihubFallbackData', 'function aihubRuntimeSnapshotRef')
    if not loader:
        loader = _section(index_src, 'async function loadAihubFallbackData', 'function aihubFallbackBadgeHtml')
    if 'ASTRA_GUI.aihubFallbackPromise' not in index_src:
        return _fail('ASTRA_GUI.aihubFallbackPromise missing')
    if 'aihubFallbackLoadedAt' not in index_src:
        return _fail('aihubFallbackLoadedAt TTL cache missing')
    if 'AIHUB_FALLBACK_TTL_MS' not in index_src:
        return _fail('AIHUB_FALLBACK_TTL_MS missing')
    if 'Promise.allSettled' not in loader:
        return _fail('loadAihubFallbackData must use Promise.allSettled')
    if 'aihubFallbackErrors' not in index_src:
        return _fail('ASTRA_GUI.aihubFallbackErrors missing')

    for endpoint in (
        '/api/debug/daily-report-pack',
        '/api/debug/final-confidence/report',
        '/api/debug/external-source-coverage',
        '/api/debug/broker-intelligence',
        '/api/debug/confidence-calibration',
        '/api/debug/market-memory/dashboard',
        '/api/debug/source-freshness',
    ):
        if endpoint not in loader:
            return _fail(f'loadAihubFallbackData missing endpoint {endpoint!r}')

    if "source-feed?source=${encodeURIComponent(src)}" not in loader and 'source-feed?source=' not in loader:
        return _fail('source-feed batch wiring missing')

    if 'runtimeSnapshotPromise' not in runtime_src:
        return _fail('runtimeSnapshotPromise singleton missing in runtimeManager.js')
    if 'runtimeRetryLoopActive' not in runtime_src:
        return _fail('runtimeRetryLoopActive guard missing in runtimeManager.js')
    if 'SNAPSHOT_FETCH_TIMEOUT_MS' not in runtime_src or '30000' not in runtime_src:
        return _fail('snapshot timeout must be 30s (SNAPSHOT_FETCH_TIMEOUT_MS)')

    retry_section = _section(runtime_src, 'async function fetchSnapshotWithRetry', 'async function refresh')
    if retry_section.count('async function fetchSnapshotWithRetry') > 1:
        return _fail('duplicate fetchSnapshotWithRetry definitions')
    if 'runtimeSnapshotPromise' not in retry_section:
        return _fail('fetchSnapshotWithRetry must dedupe via runtimeSnapshotPromise')

    header = _section(index_src, 'class="header-grid"', 'class="header-body-boundary"')
    if not header:
        return _fail('header-grid section missing')
    if 'astraedge-logo-wide.png' not in index_src and 'astraedge-logo-img' not in index_src:
        return _fail('logo markup missing')

    brand_css = _section(index_src, '.brand-fallback {', '}')
    if not brand_css:
        return _fail('.brand-fallback CSS missing')
    for token in BRAND_FALLBACK_CSS:
        if token not in brand_css:
            return _fail(f'.brand-fallback missing accessible hidden rule: {token!r}')

    if re.search(r'<div class="topbar">', index_src):
        return _fail('header redesign detected — legacy topbar must not return')

    print('FETCH_STORM_REPAIR_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
