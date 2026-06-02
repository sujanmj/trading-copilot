#!/usr/bin/env python3
"""
Validate Stage 44AK — AI Hub fallback polish (stale banner, TTL, Reddit empty, market mode, lifecycle).

Prints exactly AIHUB_FALLBACK_POLISH_OK on success.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INDEX = PROJECT_ROOT / 'frontend' / 'index.html'
RUNTIME = PROJECT_ROOT / 'frontend' / 'runtime' / 'runtimeManager.js'

MARKER = 'GUI_BUILD_STAGE_44AK_AIHUB_FALLBACK_POLISH'
FALLBACK_BADGE = 'Using report/cache fallback data'
BRAND_FALLBACK_CSS = (
    'position: absolute !important',
    'width: 1px !important',
    'clip: rect(0, 0, 0, 0) !important',
)


def _fail(msg: str) -> int:
    print(f'AIHUB_FALLBACK_POLISH_FAIL: {msg}', file=sys.stderr)
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
    if not RUNTIME.is_file():
        return _fail('frontend/runtime/runtimeManager.js missing')

    src = INDEX.read_text(encoding='utf-8')
    runtime_src = RUNTIME.read_text(encoding='utf-8')

    if MARKER not in src:
        return _fail(f'{MARKER} marker missing')

    ttl_match = re.search(r'AIHUB_FALLBACK_TTL_MS\s*=\s*(\d+)', src)
    if not ttl_match:
        return _fail('AIHUB_FALLBACK_TTL_MS missing')
    if int(ttl_match.group(1)) < 120000:
        return _fail('AIHUB_FALLBACK_TTL_MS must be >= 120000')

    if 'function activeAihubTabHasFallbackData' not in src:
        return _fail('activeAihubTabHasFallbackData missing')

    banner_fn = _section(src, 'function updateRuntimeDegradedBanner', 'function staleIntelligenceFallbackHtml')
    if 'runtime-stale-banner' not in banner_fn:
        return _fail('updateRuntimeDegradedBanner must reference runtime-stale-banner guard')
    if 'activeAihubTabHasFallbackData' not in banner_fn:
        return _fail('stale banner must be suppressed when activeAihubTabHasFallbackData')
    if FALLBACK_BADGE not in banner_fn and FALLBACK_BADGE not in src:
        return _fail(f'fallback badge missing: {FALLBACK_BADGE!r}')

    if 'No Reddit cache yet' not in src:
        return _fail('Reddit clean empty state missing')
    if 'Use Refresh Tab or open Reddit source.' not in src and 'Use Refresh Intelligence or open Reddit source.' not in src:
        return _fail('Reddit empty-state hint missing')

    if 'function aihubMarketModeFromFallback' not in src:
        return _fail('aihubMarketModeFromFallback missing')
    if 'INDIA' not in src or 'Research Mode' not in src:
        return _fail('market mode fallback mapping missing')
    if 'Loading market mode...' not in src:
        return _fail('Loading market mode placeholder missing')

    if 'Lifecycle data unavailable.' not in src:
        return _fail('Lifecycle ops-only note missing')
    if 'function isOnlyLifecycleStale' not in runtime_src:
        return _fail('isOnlyLifecycleStale missing in runtimeManager.js')
    degraded_fn = _section(runtime_src, 'function runtimeDegradedBannerHtml', 'function getHydrationPhase')
    if 'isOnlyLifecycleStale' not in degraded_fn:
        return _fail('runtimeDegradedBannerHtml must respect isOnlyLifecycleStale')

    tab_wire = _section(src, 'document.querySelectorAll(\'.tab\')', 'safeBind(\'predDetailClose\'')
    if 'ensureAihubFallbackLoaded' in tab_wire:
        return _fail('tab switch must not call ensureAihubFallbackLoaded')

    header = _section(src, 'class="header-grid"', 'class="header-body-boundary"')
    if not header:
        return _fail('header-grid section missing')
    logo_before = src.find('astraedge-logo')
    header_start = src.find('class="header-grid"')
    if header_start >= 0 and logo_before >= 0:
        logo_ctx = src[max(0, logo_before - 200):logo_before + 200]
        if 'header-grid' in logo_ctx:
            pass
    brand_css = _section(src, '.brand-fallback {', '}')
    if brand_css:
        for token in BRAND_FALLBACK_CSS:
            if token not in brand_css:
                return _fail(f'.brand-fallback missing rule: {token!r}')

    print('AIHUB_FALLBACK_POLISH_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
