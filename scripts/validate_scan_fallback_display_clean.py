#!/usr/bin/env python3
"""
Validate Stage 44AP — Scan tab memory fallback display cleanup.

Prints exactly SCAN_FALLBACK_DISPLAY_CLEAN_OK on success.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INDEX = PROJECT_ROOT / 'frontend' / 'index.html'

MARKER = 'GUI_BUILD_STAGE_44AP_SCAN_FALLBACK_DISPLAY_CLEAN'
MEMORY_LABEL = 'Memory fallback rows are shadow signals, not live scanner prices.'
MEMORY_SIGNAL = 'Memory signal'
NO_LIVE_PRICE = 'No live price attached'


def _fail(msg: str) -> int:
    print(f'SCAN_FALLBACK_DISPLAY_CLEAN_FAIL: {msg}', file=sys.stderr)
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

    if 'patchScanFallbackDisplayClean44AP' not in src:
        return _fail('patchScanFallbackDisplayClean44AP missing')

    if 'patchScanFallbackDisplayClean44AP()' not in src:
        return _fail('patchScanFallbackDisplayClean44AP must be invoked from wireCoreUi')

    for fn in (
        'isMemoryFallbackScanRow',
        'hasValidLiveScanPrice',
        'formatScanRowDisplay',
        'resolveScanOverviewMode',
        'scanRowSourceTokens',
    ):
        if f'function {fn}' not in src:
            return _fail(f'{fn} missing')

    helper_block = _section(src, 'const MEMORY_SCAN_SOURCE_KEYS', 'function aihubCollectScannerFallbackItems')
    if not helper_block:
        return _fail('44AP helper block missing')

    for token in (
        'market-memory',
        'memory',
        'runtime_snapshot_active_predictions',
        MEMORY_SIGNAL,
        NO_LIVE_PRICE,
        'INDIA_MODE',
        'INDIA_POSTMARKET_MODE',
        'RESEARCH_MODE',
        'final_confidence',
        'market_mode',
    ):
        if token not in helper_block:
            return _fail(f'helper block missing: {token!r}')

    panel = _section(src, 'function renderAihubFallbackScannerPanel', 'function aihubMarketsFallbackPayload')
    if not panel:
        return _fail('renderAihubFallbackScannerPanel missing')

    if 'formatScanRowDisplay' not in panel:
        return _fail('renderAihubFallbackScannerPanel must use formatScanRowDisplay')

    if 'resolveScanOverviewMode' not in panel:
        return _fail('renderAihubFallbackScannerPanel must use resolveScanOverviewMode')

    if MEMORY_LABEL not in panel:
        return _fail(f'memory fallback label missing: {MEMORY_LABEL!r}')

    if 'renderSignalRow(s, cls)' in panel:
        return _fail('fallback panel must not call renderSignalRow directly')

    mem_fmt = _section(src, 'function formatScanRowDisplay', 'function patchScanFallbackDisplayClean44AP')
    if MEMORY_SIGNAL not in mem_fmt or NO_LIVE_PRICE not in mem_fmt:
        return _fail('formatScanRowDisplay must show memory signal labels')

    if 'Rs.${price' in mem_fmt or 'Rs.0' in mem_fmt:
        return _fail('formatScanRowDisplay memory branch must not render Rs.0 price')

    if 'vol ${volRatio' in mem_fmt and 'isMemoryFallbackScanRow' not in mem_fmt:
        return _fail('formatScanRowDisplay must branch memory vs live before volume display')

    load_scanner = _section(src, 'function loadScanner()', 'function loadMarkets')
    if 'renderAihubFallbackScannerPanel' not in load_scanner:
        return _fail('loadScanner must use renderAihubFallbackScannerPanel fallback')

    print('SCAN_FALLBACK_DISPLAY_CLEAN_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
