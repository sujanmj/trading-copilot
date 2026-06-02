#!/usr/bin/env python3
"""
Validate Stage 44AM — final GUI cleanup (Memory confidence, historical learning,
Calib fallback, Reddit empty state, broker disclaimer, tab cache badges).

Prints exactly FINAL_GUI_CLEANUP_OK on success.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INDEX = PROJECT_ROOT / 'frontend' / 'index.html'

MARKER = 'GUI_BUILD_STAGE_44AM_FINAL_GUI_CLEANUP'
FC_ERR = 'Final confidence report unavailable — run generate_final_confidence_report.py'
CALIB_MSG = 'Live sample low — showing report/history calibration.'
REDDIT_URL = 'https://www.reddit.com/r/IndianStockMarket/'


def _fail(msg: str) -> int:
    print(f'FINAL_GUI_CLEANUP_FAIL: {msg}', file=sys.stderr)
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

    if 'patchFinalGuiCleanup44AM' not in src:
        return _fail('patchFinalGuiCleanup44AM missing')
    if 'patchTextDataCleanup44AF' in src:
        return _fail('legacy patchTextDataCleanup44AF must be replaced')

    patch_block = _section(src, 'function patchFinalGuiCleanup44AM', 'function patchFreshnessRouterOnly')
    if not patch_block:
        return _fail('patchFinalGuiCleanup44AM block missing')

    # Fix 1 — broker duplicate disclaimer
    if '.bi-shadow-label' not in patch_block:
        return _fail('broker patch must remove .bi-shadow-label duplicates')
    if patch_block.count('External broker/app evidence') > 0:
        return _fail('broker disclaimer must not be re-injected in patch (keep panel yellow disclaimer only)')

    # Fix 2 — Memory final confidence
    if '/api/debug/final-confidence/report' not in patch_block:
        return _fail('final-confidence report endpoint missing in patch')
    if '/api/debug/daily-report-pack' not in patch_block:
        return _fail('daily-report-pack fallback missing for final confidence')
    if FC_ERR not in patch_block:
        return _fail(f'missing final confidence error message: {FC_ERR!r}')
    if 'data/final_confidence_report.json' in patch_block:
        return _fail('static file fallback must use daily-report-pack API instead')

    # Fix 3 — historical learning fallbacks
    if 'Historical learning unavailable' in patch_block:
        return _fail('patch must not force Historical learning unavailable message')
    for token in (
        '/api/debug/historical-learning',
        '/api/debug/market-memory/dashboard',
        '/api/debug/confidence-calibration',
        'resolveHistoricalLearning44AM',
        'enrichMemoryHistoricalLearning44AM',
    ):
        if token not in patch_block:
            return _fail(f'historical learning fallback missing: {token!r}')

    # Fix 4 — Calib tab fallback
    if 'resolveCalibFallbackMetrics' not in src:
        return _fail('resolveCalibFallbackMetrics missing')
    if CALIB_MSG not in src:
        return _fail(f'calib fallback message missing: {CALIB_MSG!r}')
    stats_cfg = _section(src, "stats: {", 'history: {')
    if '/api/debug/market-memory/dashboard' not in stats_cfg:
        return _fail('stats tab config must include market-memory/dashboard')
    if '/api/debug/daily-report-pack' not in stats_cfg:
        return _fail('stats tab config must include daily-report-pack')

    # Fix 5 — Reddit tab
    if 'redditEmptyStateHtml' not in src:
        return _fail('redditEmptyStateHtml missing')
    if 'No Reddit cache yet' not in src:
        return _fail('Reddit empty title missing')
    if 'Open Reddit Source' not in src:
        return _fail('Open Reddit Source button missing')
    if REDDIT_URL not in src:
        return _fail(f'Reddit source URL missing: {REDDIT_URL}')
    if 'wireRedditEmptyStateActions' not in src:
        return _fail('wireRedditEmptyStateActions missing')
    reddit_collect = _section(src, 'function aihubCollectRedditFallbackItems', 'function aihubCollectTvFallbackItems')
    if 'external_evidence.social' not in reddit_collect and 'social' not in reddit_collect:
        return _fail('Reddit fallback must collect social/reddit from external-source-coverage')

    # Fix 6 — single tab cache badge
    if 'dedupeAihubTabCacheBadges' not in src:
        return _fail('dedupeAihubTabCacheBadges missing')
    stale_fn = _section(src, 'function staleBadgeHtml', 'function pickSourceTimestamp')
    if 'aihubTabCacheBadgeHtml()' in stale_fn:
        return _fail('staleBadgeHtml must not duplicate Using tab cache badge')
    degraded_fn = _section(src, 'function updateRuntimeDegradedBanner', 'function staleIntelligenceFallbackHtml')
    if 'aihubTabCacheBadgeHtml()' in degraded_fn:
        return _fail('updateRuntimeDegradedBanner must not duplicate Using tab cache badge')

    if src.count('Using tab cache') > 3:
        return _fail('too many hardcoded Using tab cache strings in index.html')

    print('FINAL_GUI_CLEANUP_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
