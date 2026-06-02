#!/usr/bin/env python3
"""
Validate Stage 44AV — kill legacy memory/broker visible render paths.

Prints exactly KILL_OLD_MEMORY_BROKER_RENDER_OK on success.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

INDEX = PROJECT_ROOT / 'frontend' / 'index.html'
GUI_SPEC = PROJECT_ROOT / 'tests' / 'gui' / 'aihub-smoke.spec.js'

MARKER = 'GUI_BUILD_STAGE_44AV_KILL_OLD_MEMORY_BROKER_RENDER'
REMOVED_BROKER_SENTENCE = 'Market and macro headlines are context only — not stock picks.'
MEMORY_SUMMARIES = (
    'Final Confidence Summary',
    'Tomorrow Watchlist Summary',
    'Calibration Summary',
)
MEMORY_BAD_TOKENS = ('Unexpected token', '<!DOCTYPE', 'Market Memory dashboard unavailable')
MEMORY_ENDPOINT = '/api/debug/daily-report-pack'
DEV_OPS_SUMMARY = 'Developer / Ops — Broker collect'
REPORT_PATHS_SUMMARY = 'Report file paths'


def _fail(msg: str) -> int:
    print(f'KILL_OLD_MEMORY_BROKER_RENDER_FAIL: {msg}', file=sys.stderr)
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
    if 'patchKillOldMemoryBrokerRender44AV' not in index_src:
        return _fail('patchKillOldMemoryBrokerRender44AV missing')
    if 'patchKillOldMemoryBrokerRender44AV()' not in index_src:
        return _fail('patchKillOldMemoryBrokerRender44AV must be invoked from wireCoreUi')

    patch_block = _section(
        index_src,
        'function patchKillOldMemoryBrokerRender44AV',
        'function patchFreshnessRouterOnly',
    )
    if not patch_block:
        return _fail('patchKillOldMemoryBrokerRender44AV block missing')

    # 44AV must run after 44AU in wireCoreUi
    au_pos = index_src.find('patchMemoryApiScanMixFix44AU()')
    av_pos = index_src.find('patchKillOldMemoryBrokerRender44AV()')
    if au_pos < 0 or av_pos < 0 or av_pos <= au_pos:
        return _fail('patchKillOldMemoryBrokerRender44AV must run after patchMemoryApiScanMixFix44AU')

    for fn in (
        'ensureMemoryVisibleSummaries44AV',
        'resolveMemoryPack44AV',
        'paintMemoryVisibleSummaries44AV',
        'scrubBrokerLegacyVisible44AV',
        'collapseBrokerDevOps44AV',
        'scheduleBrokerScrub44AV',
        'astraFetchJson',
    ):
        if fn not in patch_block:
            return _fail(f'missing 44AV helper: {fn!r}')

    for label in MEMORY_SUMMARIES:
        if label not in patch_block:
            return _fail(f'memory summary label missing in 44AV patch: {label!r}')

    if REPORT_PATHS_SUMMARY not in patch_block:
        return _fail('44AV must collapse report file paths under details summary')

    for token in MEMORY_BAD_TOKENS:
        if token not in patch_block:
            return _fail(f'44AV must handle bad memory token: {token!r}')

    if MEMORY_ENDPOINT not in patch_block:
        return _fail(f'44AV must fetch daily report pack via {MEMORY_ENDPOINT!r}')

    if "fetch('/api/" in patch_block or 'fetch(`/api/' in patch_block:
        return _fail('44AV patch must not use raw fetch(/api/...)')

    if REMOVED_BROKER_SENTENCE in patch_block:
        return _fail('44AV patch must not re-insert removed broker disclaimer sentence')

    for token in (
        'isBrokerDisclaimerText44AV',
        'bi-context-disclaimer',
        'Market-wide',
        'Macro-wide',
        DEV_OPS_SUMMARY,
        'broker-dev-ops-44av',
        'bi-import-box',
        '__render44avPatched',
        '__MEMORY_VISIBLE_OBS_44AV__',
        '__BROKER_SCRUB_OBS_44AV__',
    ):
        if token not in patch_block:
            return _fail(f'44AV broker/memory scrub token missing: {token!r}')

    if 'MarketMemoryPanel.renderInto' not in patch_block:
        return _fail('44AV must wrap MarketMemoryPanel.renderInto')
    if 'BrokerIntelligencePanel.renderInto' not in patch_block:
        return _fail('44AV must wrap BrokerIntelligencePanel.renderInto')

    if not GUI_SPEC.is_file():
        return _fail('tests/gui/aihub-smoke.spec.js missing')
    spec_src = GUI_SPEC.read_text(encoding='utf-8')
    for token in (
        *MEMORY_SUMMARIES,
        *MEMORY_BAD_TOKENS,
        REMOVED_BROKER_SENTENCE,
        'Market-wide',
        'Macro-wide',
        'Market context',
        'Macro context',
    ):
        if token not in spec_src:
            return _fail(f'playwright spec missing token: {token!r}')

    print('KILL_OLD_MEMORY_BROKER_RENDER_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
