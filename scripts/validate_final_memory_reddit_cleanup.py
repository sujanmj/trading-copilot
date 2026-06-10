#!/usr/bin/env python3
"""
Validate Stage 44AN — final memory / Reddit cleanup.

Prints exactly FINAL_MEMORY_REDDIT_CLEANUP_OK on success.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INDEX = PROJECT_ROOT / 'frontend' / 'index.html'

MARKER = 'GUI_BUILD_STAGE_44AN_FINAL_MEMORY_REDDIT_CLEANUP'
FC_ERR = 'Final confidence report unavailable — run generate_final_confidence_report.py'
HL_FALLBACK = 'Historical learning fallback'
REDDIT_URL = 'https://www.reddit.com/r/IndianStockMarket/'
BROKER_SHADOW_HIDE = '#brokersMainContent .bi-shadow-label{display:none!important}'


def _fail(msg: str) -> int:
    print(f'FINAL_MEMORY_REDDIT_CLEANUP_FAIL: {msg}', file=sys.stderr)
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

    if 'patchFinalMemoryRedditCleanup44AN' not in src:
        return _fail('patchFinalMemoryRedditCleanup44AN missing')

    patch_block = _section(src, 'function patchFinalMemoryRedditCleanup44AN', 'function patchFreshnessRouterOnly')
    if not patch_block:
        return _fail('patchFinalMemoryRedditCleanup44AN block missing')

    if 'patchFinalMemoryRedditCleanup44AN()' not in src:
        return _fail('patchFinalMemoryRedditCleanup44AN must be invoked from wireCoreUi')

    # Fix 1 — broker duplicate disclaimer
    if BROKER_SHADOW_HIDE not in patch_block:
        return _fail('broker shadow-label CSS hide missing')
    if 'dedupeBrokerDisclaimerOnce' not in patch_block:
        return _fail('dedupeBrokerDisclaimerOnce missing')
    if patch_block.count('External broker/app evidence') > 0:
        return _fail('44AN patch must not re-inject broker disclaimer text')

    # Fix 2 — Memory final confidence compact render + fallbacks
    for token in (
        '/api/debug/final-confidence/report',
        '/api/debug/daily-report-pack',
        FC_ERR,
        'renderFinalConfidenceCompact44AN',
        'loadFinalConfidenceIntoMemory44AN',
        'scheduleFinalConfidenceWatchdog44AN',
        'checked',
        'Calibration:',
    ):
        if token not in patch_block:
            return _fail(f'final confidence patch missing: {token!r}')

    if 'Loading final confidence…' not in patch_block:
        return _fail('final confidence loading guard text missing')

    # Fix 3 — historical learning fallbacks
    if 'Historical learning data unavailable.' in patch_block:
        return _fail('44AN patch must not keep Historical learning data unavailable message')
    for token in (
        '/api/debug/historical-learning',
        '/api/debug/market-memory/dashboard',
        '/api/debug/confidence-calibration',
        HL_FALLBACK,
        'resolveHistoricalLearning44AN',
        'enrichMemoryHistoricalLearning44AN',
        'by_confidence',
        'by_signal_type',
        'by_horizon',
    ):
        if token not in patch_block:
            return _fail(f'historical learning fallback missing: {token!r}')

    # Fix 4 — Reddit tab removed in Stage 50A (My Feed replaces personal screenshot ingest)
    if 'data-tab="reddit"' in src:
        return _fail('Reddit AI Hub tab must be removed in Stage 50A')
    if 'myFeedMainContent' not in src:
        return _fail('My Feed panel missing after Reddit removal')

    # Fix 5 — single tab cache badge
    if 'dedupeAihubTabCacheBadges' not in src:
        return _fail('dedupeAihubTabCacheBadges missing')
    inject_fn = _section(src, 'function injectAihubTabToolbar', 'function renderAihubTabOnly')
    if 'dedupeAihubTabCacheBadges(container)' not in inject_fn:
        return _fail('injectAihubTabToolbar must dedupe cache badges after inject')

    print('FINAL_MEMORY_REDDIT_CLEANUP_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
