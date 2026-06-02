#!/usr/bin/env python3
"""
Validate Stage 44AT — final visible 3 fixes (Market, Broker, Memory).

Prints exactly FINAL_VISIBLE_3_FIXES_OK on success.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

INDEX = PROJECT_ROOT / 'frontend' / 'index.html'
PAYLOADS = PROJECT_ROOT / 'backend' / 'analytics' / 'aihub_tab_payloads.py'
API_SERVER = PROJECT_ROOT / 'backend' / 'api' / 'api_server.py'
GUI_SPEC = PROJECT_ROOT / 'tests' / 'gui' / 'aihub-smoke.spec.js'

MARKER = 'GUI_BUILD_STAGE_44AT_FINAL_VISIBLE_3_FIXES'
CLOSED_NOTE = 'Closed-market snapshot — review only, not live entry.'
UNDERLYING_STALE = 'Underlying market data is stale.'
REFRESH_CMD = 'refresh_closed_market_intelligence.py'
CONTEXT_DISCLAIMER = 'context only — not stock picks'
MEMORY_SUMMARIES = (
    'Final Confidence Summary',
    'Tomorrow Watchlist Summary',
    'Calibration Summary',
    'Report file paths',
)
BROKER_FORBIDDEN = ('Market-wide', 'Macro-wide')
MARKET_TS_TOKENS = (
    'Snapshot refreshed at',
    'Market data timestamp',
    'Refresh attempted',
    'Last available snapshot',
)


def _fail(msg: str) -> int:
    print(f'FINAL_VISIBLE_3_FIXES_FAIL: {msg}', file=sys.stderr)
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
    if not PAYLOADS.is_file():
        return _fail('backend/analytics/aihub_tab_payloads.py missing')
    if not API_SERVER.is_file():
        return _fail('backend/api/api_server.py missing')

    index_src = INDEX.read_text(encoding='utf-8')
    payloads_src = PAYLOADS.read_text(encoding='utf-8')
    api_src = API_SERVER.read_text(encoding='utf-8')

    if MARKER not in index_src:
        return _fail(f'{MARKER} marker missing')

    if 'patchFinalVisible3Fixes44AT' not in index_src:
        return _fail('patchFinalVisible3Fixes44AT missing')
    if 'patchFinalVisible3Fixes44AT()' not in index_src:
        return _fail('patchFinalVisible3Fixes44AT must be invoked from wireCoreUi')

    patch_block = _section(index_src, 'function patchFinalVisible3Fixes44AT', 'function patchFreshnessRouterOnly')
    if not patch_block:
        return _fail('patchFinalVisible3Fixes44AT block missing')

    ui_tokens = [
        'renderMemorySummaries44AT',
        'drp-memory-summary',
        'drp-report-paths-details',
        'Report file paths',
        *MEMORY_SUMMARIES,
        'rebuildBrokerContextSections44AT',
        'bi-context-card',
        'bi-context-disclaimer',
        CONTEXT_DISCLAIMER,
        'marketTimestampsHtml44AT',
        'Snapshot refreshed at',
        'Market data timestamp',
        'Refresh attempted',
        'Last available snapshot',
        'MARKET_STALE_CMD_44AT',
        CLOSED_NOTE,
        'UNDERLYING_STALE_NOTE_44AT',
        '?force=1',
        'applyMarketTimestamps44AT',
        'loadAihubTabData',
        'marketRefreshMeta',
    ]
    for token in ui_tokens:
        if token not in patch_block and token not in index_src:
            return _fail(f'missing UI token: {token!r}')

    for label in BROKER_FORBIDDEN:
        if f"tickerCell.textContent = '{label}'" in patch_block:
            return _fail(f'broker patch must not assign visible {label!r}')

    if 'force: int = Query(0)' not in api_src:
        return _fail('api route must accept force query param')
    if 'bool(force or refresh)' not in api_src:
        return _fail('api route must pass force or refresh to build_aihub_tab_payload')

    for token in (
        'def build_market_payload(*, force: bool = False)',
        'MARKET_FORCE_REFRESH_TIMEOUT_SEC',
        'UNDERLYING_DATA_STALE_NOTE',
        '_try_safe_market_force_refresh',
        'snapshot_refreshed_at',
        'market_data_timestamp',
        'underlying_data_stale',
        'refresh_attempted_at',
        'build_market_payload(force=True)',
    ):
        if token not in payloads_src:
            return _fail(f'backend payloads missing: {token!r}')

    if REFRESH_CMD not in payloads_src:
        return _fail('MARKET_STALE_REFRESH_CMD missing')

    try:
        from backend.analytics.aihub_tab_payloads import (
            CLOSED_MARKET_NOTE,
            UNDERLYING_DATA_STALE_NOTE,
            build_market_payload,
            build_aihub_tab_payload,
        )
    except Exception as exc:
        return _fail(f'import aihub_tab_payloads: {exc}')

    if CLOSED_MARKET_NOTE != CLOSED_NOTE:
        return _fail('CLOSED_MARKET_NOTE mismatch')
    if UNDERLYING_DATA_STALE_NOTE != UNDERLYING_STALE:
        return _fail('UNDERLYING_DATA_STALE_NOTE mismatch')

    market = build_market_payload()
    summary = market.get('summary') or {}
    for key in (
        'snapshot_refreshed_at',
        'market_data_timestamp',
        'underlying_data_stale',
        'market_stale',
        'market_closed',
        'manual_refresh_cmd',
    ):
        if key not in summary:
            return _fail(f'market summary must include {key!r}')

    forced = build_aihub_tab_payload('market', force_refresh=True)
    fsum = forced.get('summary') or {}
    if not fsum.get('refresh_attempted_at'):
        return _fail('force refresh must set refresh_attempted_at')

    if not GUI_SPEC.is_file():
        return _fail('tests/gui/aihub-smoke.spec.js missing')
    spec_src = GUI_SPEC.read_text(encoding='utf-8')
    for token in (
        'Final Confidence Summary',
        'Tomorrow Watchlist Summary',
        'Calibration Summary',
        'final_confidence_report.json',
        'Market-wide',
        'Macro-wide',
        CONTEXT_DISCLAIMER,
        'Snapshot refreshed at',
        'Refresh attempted',
    ):
        if token not in spec_src:
            return _fail(f'playwright spec missing: {token!r}')

    print('FINAL_VISIBLE_3_FIXES_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
