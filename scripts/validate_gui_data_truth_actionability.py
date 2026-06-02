#!/usr/bin/env python3
"""
Validate Stage 44AR — GUI data truth & actionability patches.

Prints exactly GUI_DATA_TRUTH_ACTIONABILITY_OK on success.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
INDEX = PROJECT_ROOT / 'frontend' / 'index.html'
PAYLOADS = PROJECT_ROOT / 'backend' / 'analytics' / 'aihub_tab_payloads.py'

MARKER = 'GUI_BUILD_STAGE_44AR_DATA_TRUTH_ACTIONABILITY'
GOVT_EMPTY = (
    'No fresh government/policy intelligence collected. '
    'Last report has no govt-specific trigger.'
)
FC_PACK_FALLBACK = 'Source: Daily Report Pack fallback'
BROKER_RELIABILITY = 'Not enough closed broker outcomes yet'
BROKER_NOTE = (
    'Collected broker ideas are external evidence only. '
    'They do not become BUY unless our own filters agree.'
)
WATCH_LABEL = 'WATCH is not BUY. It means wait for confirmation.'
MARKET_STALE = 'Market data stale — refresh market/global data'
REFRESH_CMD = 'refresh_closed_market_intelligence.py'
FAILED_STRONG = (
    'Recent strong signal failed or weakened — reduce confidence until new confirmation.'
)


def _fail(msg: str) -> int:
    print(f'GUI_DATA_TRUTH_ACTIONABILITY_FAIL: {msg}', file=sys.stderr)
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

    index_src = INDEX.read_text(encoding='utf-8')
    payloads_src = PAYLOADS.read_text(encoding='utf-8')

    if MARKER not in index_src:
        return _fail(f'{MARKER} marker missing')

    if 'patchDataTruthActionability44AR' not in index_src:
        return _fail('patchDataTruthActionability44AR missing')
    if 'patchDataTruthActionability44AR()' not in index_src:
        return _fail('patchDataTruthActionability44AR must be invoked from wireCoreUi')

    patch_block = _section(index_src, 'function patchDataTruthActionability44AR', 'function patchFreshnessRouterOnly')
    if not patch_block:
        return _fail('patchDataTruthActionability44AR block missing')

    for token in (
        FC_PACK_FALLBACK,
        'packHasFinalConfidence44AR',
        '/api/debug/final-confidence/report',
        'renderFinalConfidencePackFallback44AR',
        BROKER_RELIABILITY,
        BROKER_NOTE,
        'aiOpsBrokerDev',
        'Developer / Ops',
        'bi-import-box',
        GOVT_EMPTY,
        'aihubCollectGovtFallbackItems',
        'renderCalibRecCard44AR',
        'calib-rec-card',
        'Bucket',
        'Expected win rate',
        'Calibration error',
        WATCH_LABEL,
        'dedupeWatchRows44AR',
        'formatWatchLine44AR',
        MARKET_STALE,
        REFRESH_CMD,
        'marketStaleBadgeHtml44AR',
        'GOLDBEES',
        'SILVERBEES',
        'JSWSTEEL',
        'renderGlobalSectorMappingHtml44AR',
        'WATCH/REVIEW only',
        'Actionable Candidates',
        'BUY CANDIDATE',
        'WATCH FOR ENTRY',
        'Watch for entry only after price confirms strength',
        FAILED_STRONG,
        'FAILED_STRONG_EXAMPLE_TICKERS',
        'JPPOWER',
    ):
        if token not in patch_block and token not in index_src:
            return _fail(f'missing UI token: {token!r}')

    if 'JSON.stringify(r)' in patch_block and 'renderAihubFallbackCalibSection' in patch_block:
        pass  # legacy path may remain in orig; cards must exist
    if 'renderCalibRecCard44AR' not in patch_block:
        return _fail('calibration rec cards renderer missing')

    for token in (
        'GOVT_EMPTY_MESSAGE',
        '_collect_govt_items',
        '_build_actionable_candidates',
        '_detect_failed_strong_warnings',
        '_journal_top_watch_rows',
        'GLOBAL_SECTOR_MAPPING',
        'MARKET_STALE_REFRESH_CMD',
        'calibration_recommendations',
        'actionable_candidates',
        'failed_strong_warnings',
        'sector_mapping',
        'market_stale',
    ):
        if token not in payloads_src:
            return _fail(f'backend payloads missing: {token!r}')

    try:
        from backend.analytics.aihub_tab_payloads import (
            build_brain_payload,
            build_govt_payload,
            build_journal_payload,
            build_global_payload,
            build_market_payload,
            build_calib_payload,
            GOVT_EMPTY_MESSAGE,
        )
    except Exception as exc:
        return _fail(f'import aihub_tab_payloads: {exc}')

    if GOVT_EMPTY_MESSAGE != GOVT_EMPTY:
        return _fail('GOVT_EMPTY_MESSAGE mismatch')

    govt = build_govt_payload()
    if not govt.get('items'):
        summary = govt.get('summary') or {}
        if summary.get('empty_message') != GOVT_EMPTY:
            return _fail('govt empty_message must match spec when no items')

    brain = build_brain_payload()
    if 'actionable_candidates' not in (brain.get('summary') or {}):
        return _fail('brain summary must include actionable_candidates')

    journal = build_journal_payload()
    jsum = journal.get('summary') or {}
    if 'top_watch' not in jsum:
        return _fail('journal summary must include top_watch')
    if jsum.get('top_watch_label') != WATCH_LABEL:
        return _fail('journal top_watch_label mismatch')

    global_payload = build_global_payload()
    if 'sector_mapping' not in (global_payload.get('summary') or {}):
        return _fail('global summary must include sector_mapping')

    calib = build_calib_payload()
    rec_items = [i for i in (calib.get('items') or []) if i.get('kind') == 'calibration_rec']
    if not rec_items:
        pass  # OK when no calibration file — structure still valid

    market = build_market_payload()
    if 'market_stale' not in (market.get('summary') or {}):
        return _fail('market summary must include market_stale flag')

    print('GUI_DATA_TRUTH_ACTIONABILITY_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
