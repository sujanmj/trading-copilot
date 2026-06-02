#!/usr/bin/env python3
"""
Validate Stage 44AO — Memory tab async fallback fix.

Prints exactly MEMORY_ASYNC_FIX_OK on success.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INDEX = PROJECT_ROOT / 'frontend' / 'index.html'

MARKER = 'GUI_BUILD_STAGE_44AO_MEMORY_ASYNC_FIX'
FC_FILE_SOURCE = 'data/final_confidence_report.json'
HL_FALLBACK = 'Historical learning fallback'
PERMANENT_LOADING = (
    '⏳ Loading final confidence…',
    'Loading historical learning…',
)


def _fail(msg: str) -> int:
    print(f'MEMORY_ASYNC_FIX_FAIL: {msg}', file=sys.stderr)
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

    if 'patchMemoryAsyncFix44AO' not in src:
        return _fail('patchMemoryAsyncFix44AO missing')

    if 'patchMemoryAsyncFix44AO()' not in src:
        return _fail('patchMemoryAsyncFix44AO must be invoked from wireCoreUi')

    patch_block = _section(src, 'function patchMemoryAsyncFix44AO', 'function patchFreshnessRouterOnly')
    if not patch_block:
        return _fail('patchMemoryAsyncFix44AO block missing')

    # Fix 1 — sync daily-pack final confidence fallback + optional async upgrade
    for token in (
        'getSyncDailyReportPack44AO',
        'buildFinalConfidenceSync44AO',
        'daily-report-pack',
        'final_confidence',
        'pack.summary',
        'pack.files',
        'renderFinalConfidenceCompact44AO',
        'loadFinalConfidenceIntoMemory44AO',
        'applyFinalConfidenceSyncFallback44AO',
        '/api/debug/final-confidence/report',
        '/api/debug/daily-report-pack',
        FC_FILE_SOURCE,
        'Calibration recs',
        'Simulation:',
        'Mode',
        'Checked',
        'Buy',
        'Watch',
        'Avoid',
        'No decision',
    ):
        if token not in patch_block:
            return _fail(f'final confidence sync fallback missing: {token!r}')

    if 'applyFinalConfidenceSyncFallback44AO(target)' not in patch_block:
        return _fail('final confidence must render sync fallback before async fetch')

    # Fix 2 — historical learning sync fallback from market memory dashboard
    for token in (
        'getSyncMarketMemoryDash44AO',
        'buildHistoricalLearningSync44AO',
        'market-memory/dashboard',
        'by_confidence_label',
        'by_confidence',
        'by_signal_type',
        'by_prediction_horizon',
        'renderMmHistoricalLearningCompact44AO',
        'applyHistoricalLearningSyncFallback44AO',
        'enrichMemoryHistoricalLearning44AO',
        '/api/debug/historical-learning',
        HL_FALLBACK,
        'Predictions',
        'Outcomes',
        'Win rate',
        'Wins / Losses',
        'confidence_calibration',
    ):
        if token not in patch_block:
            return _fail(f'historical learning sync fallback missing: {token!r}')

    if 'applyHistoricalLearningSyncFallback44AO()' not in patch_block:
        return _fail('historical learning must apply sync fallback before async enrich')

    # Fix 3 — async safety
    for token in (
        'astraFetchJson',
        'Promise.allSettled',
        'scheduleMemoryAsyncEnrich44AO',
        'applyMemorySyncFallbacks44AO',
        '__MEMORY_SYNC_PACK_CACHE__',
    ):
        if token not in patch_block:
            return _fail(f'async safety missing: {token!r}')

    if patch_block.count('innerHTML = \'<div class="loading">⏳ Loading final confidence') > 0:
        return _fail('44AO patch must not set permanent final-confidence loading placeholder')

    if 'emptyNode.textContent = \'Loading historical learning' in patch_block:
        return _fail('44AO patch must not set permanent historical-learning loading text')

    # Fix 4 — no permanent loading strings in static HTML (Memory patch scope)
    static_html = _section(src, '<div class="workspace-panel workspace-memory', '<script src="components/MarketMemoryPanel.js">')
    for loading in PERMANENT_LOADING:
        if loading in static_html:
            return _fail(f'permanent loading text in memory static HTML: {loading!r}')

    if 'FinalConfidencePanel.loadInto = async function' not in patch_block:
        return _fail('FinalConfidencePanel.loadInto must be patched in 44AO block')

    if 'MarketMemoryPanel.loadMain = function' not in patch_block:
        return _fail('MarketMemoryPanel.loadMain must be wrapped in 44AO block')

    print('MEMORY_ASYNC_FIX_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
