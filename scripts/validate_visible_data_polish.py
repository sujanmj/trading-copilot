#!/usr/bin/env python3
"""
Validate Stage 44AS — visible data polish (Memory, Broker, Market, GUI smoke).

Prints exactly VISIBLE_DATA_POLISH_OK on success.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

INDEX = PROJECT_ROOT / 'frontend' / 'index.html'
PAYLOADS = PROJECT_ROOT / 'backend' / 'analytics' / 'aihub_tab_payloads.py'
PKG = PROJECT_ROOT / 'frontend' / 'package.json'
GUI_SPEC = PROJECT_ROOT / 'tests' / 'gui' / 'aihub-smoke.spec.js'
PLAYWRIGHT_CFG = PROJECT_ROOT / 'frontend' / 'playwright.config.js'

MARKER = 'GUI_BUILD_STAGE_44AS_VISIBLE_DATA_POLISH'
REPORT_LABELS = (
    'Final Confidence Report',
    'Tomorrow Watchlist Report',
    'Calibration Report',
)
BROKER_LABELS = ('Market-wide', 'Macro-wide', 'Unmapped', 'Needs review')
BROKER_RELIABILITY = 'Not enough outcomes yet'
STALE_BADGE = 'Stale snapshot'
FRESH_BADGE = 'Fresh snapshot'
CLOSED_NOTE = 'Closed-market snapshot — review only, not live entry.'
REFRESH_CMD = 'refresh_closed_market_intelligence.py'


def _fail(msg: str) -> int:
    print(f'VISIBLE_DATA_POLISH_FAIL: {msg}', file=sys.stderr)
    return 1


def _section(src: str, start_marker: str, end_marker: str) -> str:
    start = src.find(start_marker)
    if start < 0:
        return ''
    end = src.find(end_marker, start + len(start_marker))
    if end < 0:
        return src[start:]
    return src[start:end]


def _playwright_status() -> str:
    if not GUI_SPEC.is_file():
        return 'playwright_gui_smoke: skipped (tests/gui/aihub-smoke.spec.js missing)'
    if not PKG.is_file():
        return 'playwright_gui_smoke: skipped (frontend/package.json missing)'
    pkg_text = PKG.read_text(encoding='utf-8')
    if 'test:gui' not in pkg_text:
        return 'playwright_gui_smoke: skipped (test:gui script missing)'
    if '@playwright/test' not in pkg_text:
        return 'playwright_gui_smoke: skipped (@playwright/test not in package.json)'
    return 'playwright_gui_smoke: configured'


def main() -> int:
    if not INDEX.is_file():
        return _fail('frontend/index.html missing')
    if not PAYLOADS.is_file():
        return _fail('backend/analytics/aihub_tab_payloads.py missing')

    index_src = INDEX.read_text(encoding='utf-8')
    payloads_src = PAYLOADS.read_text(encoding='utf-8')

    if MARKER not in index_src:
        return _fail(f'{MARKER} marker missing')

    if 'patchVisibleDataPolish44AS' not in index_src:
        return _fail('patchVisibleDataPolish44AS missing')
    if 'patchVisibleDataPolish44AS()' not in index_src:
        return _fail('patchVisibleDataPolish44AS must be invoked from wireCoreUi')

    patch_block = _section(index_src, 'function patchVisibleDataPolish44AS', 'function patchFreshnessRouterOnly')
    if not patch_block:
        return _fail('patchVisibleDataPolish44AS block missing')

    for token in (
        'renderReportFileCards44AS',
        'drp-report-file-card',
        'drp-report-file-name',
        'drp-report-file-path',
        *REPORT_LABELS,
        'fc-debug-muted',
        'GET /api/debug/daily-report-pack',
        'fixBrokerTickers44AS',
        'resolveBrokerTickerLabel44AS',
        *BROKER_LABELS,
        BROKER_RELIABILITY,
        'bi-tag-row',
        'marketStaleBannerHtml44AS',
        STALE_BADGE,
        FRESH_BADGE,
        CLOSED_NOTE,
        REFRESH_CMD,
        'market-stale-badge',
        'market-fresh-badge',
        'refreshAihubTabOnly',
        'renderAihubTabOnly',
        'applyMarketBannerToContainer44AS',
    ):
        if token not in patch_block and token not in index_src:
            return _fail(f'missing UI token: {token!r}')

    for token in (
        '_is_closed_market_mode',
        'market_closed',
        'closed_market_note',
        'Closed-market snapshot',
        'MARKET_STALE_REFRESH_CMD',
    ):
        if token not in payloads_src:
            return _fail(f'backend payloads missing: {token!r}')

    try:
        from backend.analytics.aihub_tab_payloads import (
            CLOSED_MARKET_NOTE,
            build_market_payload,
        )
    except Exception as exc:
        return _fail(f'import aihub_tab_payloads: {exc}')

    if CLOSED_MARKET_NOTE != CLOSED_NOTE:
        return _fail('CLOSED_MARKET_NOTE mismatch')

    market = build_market_payload()
    summary = market.get('summary') or {}
    if 'market_stale' not in summary:
        return _fail('market summary must include market_stale')
    if 'market_closed' not in summary:
        return _fail('market summary must include market_closed')
    if summary.get('market_closed') and summary.get('closed_market_note') != CLOSED_NOTE:
        return _fail('closed_market_note must match when market_closed')

    pw_status = _playwright_status()
    print(pw_status)
    print('VISIBLE_DATA_POLISH_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
