#!/usr/bin/env python3
"""
Validate Stage 44AH — ASTRA_GUI.aihubFallback hydration contract in frontend/index.html.

Prints exactly AIHUB_FALLBACK_HYDRATION_OK on success.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INDEX = PROJECT_ROOT / 'frontend' / 'index.html'


def _fail(msg: str) -> int:
    print(f'AIHUB_FALLBACK_HYDRATION_FAIL: {msg}', file=sys.stderr)
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

    if 'aihubFallback: null' not in src and 'aihubFallback:null' not in src.replace(' ', ''):
        return _fail('ASTRA_GUI must declare aihubFallback: null')

    loader = _section(src, 'async function loadAihubFallbackData', 'function aihubFallbackBadgeHtml')
    if not loader:
        return _fail('loadAihubFallbackData missing')

    for key in (
        'dailyReportPack',
        'finalConfidence',
        'externalCoverage',
        'brokerIntelligence',
        'sourceFeeds',
        'confidenceCalibration',
        'marketMemoryDashboard',
        'sourceFreshness',
    ):
        if key not in loader:
            return _fail(f'fallback payload key missing: {key!r}')

    if 'fb.errors' not in loader:
        return _fail('fallback loader must track per-endpoint errors')

    if 'ASTRA_GUI.aihubFallback = fb' not in loader:
        return _fail('loader must assign ASTRA_GUI.aihubFallback')

    if 'function getAihubFallback' not in src:
        return _fail('getAihubFallback helper missing')

    boot = _section(src, 'async function bootFrontend', 'async function refreshAll')
    if 'await loadAihubFallbackData()' not in boot:
        return _fail('bootFrontend must await loadAihubFallbackData()')

    refresh = _section(src, 'async function refreshAll', 'let debugOverlayOpen')
    if 'loadAihubFallbackData()' not in refresh:
        return _fail('refreshAll must reload loadAihubFallbackData()')

    if 'window.ASTRA_GUI = ASTRA_GUI' not in src:
        return _fail('ASTRA_GUI must be exported on window')

    print('AIHUB_FALLBACK_HYDRATION_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
