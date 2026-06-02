#!/usr/bin/env python3
"""
Validate Stage 44AU — Memory API base bug, scan mix, broker disclaimer removal.

Prints exactly MEMORY_API_SCAN_MIX_FIX_OK on success.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

INDEX = PROJECT_ROOT / 'frontend' / 'index.html'
PAYLOADS = PROJECT_ROOT / 'backend' / 'analytics' / 'aihub_tab_payloads.py'
API_SERVER = PROJECT_ROOT / 'backend' / 'api' / 'api_server.py'
GUI_SPEC = PROJECT_ROOT / 'tests' / 'gui' / 'aihub-smoke.spec.js'
FINAL_REPORT = PROJECT_ROOT / 'data' / 'final_confidence_report.json'

MARKER = 'GUI_BUILD_STAGE_44AU_MEMORY_API_SCAN_MIX_FIX'
REMOVED_BROKER_SENTENCE = 'Market and macro headlines are context only — not stock picks.'
MEMORY_ENDPOINTS = (
    '/api/debug/market-memory/dashboard',
    '/api/debug/daily-report-pack',
    '/api/debug/final-confidence',
    '/api/debug/final-confidence/report',
    '/api/debug/historical-learning',
    '/api/debug/confidence-calibration',
)
SCAN_SECTIONS = (
    'Live Scanner / ULTRA Moves',
    'Watchlist Candidates',
    'Memory Signals',
)
MEMORY_SUMMARIES = (
    'Final Confidence Summary',
    'Tomorrow Watchlist Summary',
    'Calibration Summary',
)


def _fail(msg: str) -> int:
    print(f'MEMORY_API_SCAN_MIX_FIX_FAIL: {msg}', file=sys.stderr)
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
    if 'patchMemoryApiScanMixFix44AU' not in index_src:
        return _fail('patchMemoryApiScanMixFix44AU missing')
    if 'patchMemoryApiScanMixFix44AU()' not in index_src:
        return _fail('patchMemoryApiScanMixFix44AU must be invoked from wireCoreUi')

    patch_block = _section(index_src, 'function patchMemoryApiScanMixFix44AU', 'function patchFreshnessRouterOnly')
    if not patch_block:
        return _fail('patchMemoryApiScanMixFix44AU block missing')

    for fn in ('astraApiUrl', 'astraFetchJson', 'memoryFetchJson44AU', 'renderScanMixPanel44AU', 'sanitizeMemoryMainContent44AU'):
        if fn not in patch_block and fn not in index_src:
            return _fail(f'missing memory/scan helper: {fn!r}')

    for path in MEMORY_ENDPOINTS:
        if path not in patch_block:
            return _fail(f'memory patch must reference {path!r}')

    if "fetch('/api/" in patch_block or 'fetch(`/api/' in patch_block:
        return _fail('memory patch must not use raw fetch(/api/...)')

    for token in ('Unexpected token', '<!DOCTYPE', 'Market Memory dashboard unavailable'):
        if token not in patch_block:
            return _fail(f'memory patch must handle bad token: {token!r}')

    for label in MEMORY_SUMMARIES:
        if label not in patch_block and label not in index_src:
            return _fail(f'memory summary label missing: {label!r}')

    for section in SCAN_SECTIONS:
        if section not in patch_block:
            return _fail(f'scan section missing in patch: {section!r}')

    if REMOVED_BROKER_SENTENCE in patch_block:
        return _fail('44AU patch must not re-insert removed broker disclaimer sentence')

    if 'bi-context-disclaimer' not in patch_block:
        return _fail('broker patch must remove bi-context-disclaimer nodes')

    for token in (
        'def _watchlist_candidate_row',
        'live_scanner',
        'watchlist_candidates',
        'memory_signals',
        'live_scanner_count',
        'watchlist_count',
        'memory_signal_count',
        'Memory signal — no live price attached',
    ):
        if token not in payloads_src:
            return _fail(f'backend payloads missing: {token!r}')

    if 'load_cached_final_confidence_report' not in api_src:
        return _fail('api_server must use cached final confidence report reader')
    if 'final_confidence_report_loader' not in api_src:
        return _fail('api_server must import final_confidence_report_loader')
    if 'get_final_confidence_dashboard(limit=limit)' in api_src:
        return _fail('final-confidence routes must not call live get_final_confidence_dashboard')

    try:
        from backend.analytics.aihub_tab_payloads import build_scan_payload

        scan = build_scan_payload()
    except Exception as exc:
        return _fail(f'build_scan_payload import/run: {exc}')

    for key in ('live_scanner', 'watchlist_candidates', 'memory_signals', 'summary'):
        if key not in scan:
            return _fail(f'scan payload missing top-level key: {key!r}')

    summary = scan.get('summary') or {}
    for key in ('live_scanner_count', 'watchlist_count', 'memory_signal_count', 'mode'):
        if key not in summary:
            return _fail(f'scan summary missing: {key!r}')

    memory_rows = scan.get('memory_signals') or []
    if memory_rows:
        sample = memory_rows[0]
        if sample.get('price') is not None:
            return _fail('memory_signals row must have price=null')
        if sample.get('display_note') != 'Memory signal — no live price attached':
            return _fail('memory_signals row missing display_note')

    wl_rows = scan.get('watchlist_candidates') or []
    if wl_rows:
        sample = wl_rows[0]
        if not sample.get('is_watchlist_candidate'):
            return _fail('watchlist_candidates must set is_watchlist_candidate=true')
        if sample.get('score') is None:
            return _fail('watchlist_candidates must include score')

    try:
        from backend.utils.config import DATA_DIR
        import json as _json

        report_path = DATA_DIR / 'final_confidence_report.json'
        t0 = time.perf_counter()
        if report_path.is_file():
            report = _json.loads(report_path.read_text(encoding='utf-8'))
            rows = report.get('rows') if isinstance(report.get('rows'), list) else report.get('top_candidates')
            cached_ok = isinstance(report, dict) and report.get('ok') is True and isinstance(rows, list)
        else:
            cached_ok = False
        elapsed = time.perf_counter() - t0
        if elapsed > 2.0:
            return _fail(f'cached final-confidence read too slow: {elapsed:.2f}s')
        if FINAL_REPORT.is_file():
            if not cached_ok:
                return _fail('final_confidence_report.json must be readable with ok=true and rows/top_candidates list')
        if '_load_cached_final_confidence_report' not in api_src and 'load_cached_final_confidence_report' not in api_src:
            return _fail('api_server must use cached final confidence report reader')
    except Exception as exc:
        return _fail(f'cached final-confidence file read: {exc}')

    if not GUI_SPEC.is_file():
        return _fail('tests/gui/aihub-smoke.spec.js missing')
    spec_src = GUI_SPEC.read_text(encoding='utf-8')
    for token in (
        'Unexpected token',
        '<!DOCTYPE',
        'Market Memory dashboard unavailable',
        'Live Scanner',
        'ULTRA Moves',
        'Watchlist Candidates',
        'Memory Signals',
        REMOVED_BROKER_SENTENCE,
    ):
        if token not in spec_src:
            return _fail(f'playwright spec missing token: {token!r}')

    print('MEMORY_API_SCAN_MIX_FIX_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
