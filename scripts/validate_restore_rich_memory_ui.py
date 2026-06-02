#!/usr/bin/env python3
"""
Validate Stage 44AW — restore rich Memory dashboard UI.

Prints exactly RESTORE_RICH_MEMORY_UI_OK on success.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

INDEX = PROJECT_ROOT / 'frontend' / 'index.html'
GUI_SPEC = PROJECT_ROOT / 'tests' / 'gui' / 'aihub-smoke.spec.js'

MARKER = 'GUI_BUILD_STAGE_44AW_RESTORE_RICH_MEMORY_UI'
MEMORY_API_PATHS = (
    '/api/debug/daily-report-pack',
    '/api/debug/market-memory/dashboard',
    '/api/debug/final-confidence/report',
)
RICH_SECTIONS = (
    'Final Confidence Summary',
    'Tomorrow Watchlist Summary',
    'Calibration Summary',
    'Canonical Market Memory Overview',
    'Shadow Advisor',
    'Latest outcomes',
    'Latest predictions',
)
MEMORY_BAD_TOKENS = ('Unexpected token', '<!DOCTYPE', 'Market Memory dashboard unavailable')
REPORT_PATHS_SUMMARY = 'Report file paths'
RICH_CLASSES = ('stat-big-card', 'mm-table', 'glass-card', 'mm-stat-grid')


def _fail(msg: str) -> int:
    print(f'RESTORE_RICH_MEMORY_UI_FAIL: {msg}', file=sys.stderr)
    return 1


def _section(src: str, start_marker: str, end_marker: str) -> str:
    start = src.find(start_marker)
    if start < 0:
        return ''
    end = src.find(end_marker, start + len(start_marker))
    if end < 0:
        return src[start:]
    return src[start:end]


def main() -> int:
    if not INDEX.is_file():
        return _fail('frontend/index.html missing')

    index_src = INDEX.read_text(encoding='utf-8')

    if MARKER not in index_src:
        return _fail(f'{MARKER} marker missing')
    if 'patchRestoreRichMemoryUi44AW' not in index_src:
        return _fail('patchRestoreRichMemoryUi44AW missing')
    if 'patchRestoreRichMemoryUi44AW()' not in index_src:
        return _fail('patchRestoreRichMemoryUi44AW must be invoked from wireCoreUi')

    av_pos = index_src.find('patchKillOldMemoryBrokerRender44AV()')
    aw_pos = index_src.find('patchRestoreRichMemoryUi44AW()')
    if av_pos < 0 or aw_pos < 0 or aw_pos <= av_pos:
        return _fail('patchRestoreRichMemoryUi44AW must run after patchKillOldMemoryBrokerRender44AV')

    patch_block = _section(index_src, 'function patchRestoreRichMemoryUi44AW', 'function patchFreshnessRouterOnly')
    if not patch_block:
        return _fail('patchRestoreRichMemoryUi44AW block missing')

    for fn in (
        'renderRichMemoryDashboard44AW',
        'ensureRichMemoryDashboard44AW',
        'paintRichMemoryDashboard44AW',
        'resolveMemoryData44AW',
        'safeMemoryFetch44AW',
        'scrubBadMemoryContent44AW',
        'isBadMemoryToken44AW',
    ):
        if fn not in patch_block:
            return _fail(f'missing 44AW helper: {fn!r}')

    for path in MEMORY_API_PATHS:
        if path not in patch_block:
            return _fail(f'44AW must fetch via astraFetchJson path: {path!r}')

    if "fetch('/api/" in patch_block or 'fetch(`/api/' in patch_block:
        return _fail('44AW patch must not use raw fetch(/api/...)')

    for label in RICH_SECTIONS:
        if label not in patch_block:
            return _fail(f'rich section label missing in 44AW patch: {label!r}')

    if REPORT_PATHS_SUMMARY not in patch_block:
        return _fail('44AW must collapse report file paths under details summary')
    if '<details' not in patch_block or 'drp-report-paths-details' not in patch_block:
        return _fail('44AW report paths must use collapsed details element')

    for token in MEMORY_BAD_TOKENS:
        if token not in patch_block:
            return _fail(f'44AW must handle bad memory token: {token!r}')

    for cls in RICH_CLASSES:
        if cls not in patch_block:
            return _fail(f'44AW must use rich UI class: {cls!r}')

    if 'MarketMemoryPanel.renderInto' not in patch_block:
        return _fail('44AW must wrap MarketMemoryPanel.renderInto')
    if '__render44awPatched' not in patch_block:
        return _fail('44AW must guard MarketMemoryPanel.renderInto wrap')
    if 'mm-44aw-rich' not in patch_block:
        return _fail('44AW rich dashboard marker class missing')

    if 'drp-memory-fallback-host' in patch_block and 'mm-44aw-rich' not in patch_block:
        return _fail('44AW must not use plain drp-memory-fallback-host as sole renderer')

    if not GUI_SPEC.is_file():
        return _fail('tests/gui/aihub-smoke.spec.js missing')
    spec_src = GUI_SPEC.read_text(encoding='utf-8')
    for token in (
        'Canonical Market Memory Overview',
        'Latest outcomes',
        'Latest predictions',
        'mm-44aw-rich',
        *MEMORY_BAD_TOKENS,
        REPORT_PATHS_SUMMARY,
    ):
        if token not in spec_src:
            return _fail(f'playwright spec missing token: {token!r}')

    print('RESTORE_RICH_MEMORY_UI_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
