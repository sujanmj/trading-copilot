#!/usr/bin/env python3
"""
Test final confidence endpoint stability (Stage 44AX).

Prints exactly FINAL_CONFIDENCE_ENDPOINT_STABILITY_TEST_OK on success.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

API_SERVER = PROJECT_ROOT / 'backend' / 'api' / 'api_server.py'
LOADER = PROJECT_ROOT / 'backend' / 'analytics' / 'final_confidence_report_loader.py'
REPORT_FILE = PROJECT_ROOT / 'data' / 'final_confidence_report.json'
MARKER = 'BACKEND_STAGE_44AX_FINAL_CONFIDENCE_ENDPOINT_STABLE'
ROUTES = (
    '/api/debug/final-confidence',
    '/api/debug/final-confidence/report',
)


def _fail(msg: str) -> int:
    print(f'FINAL_CONFIDENCE_ENDPOINT_STABILITY_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    if not LOADER.is_file():
        return _fail('final_confidence_report_loader.py missing')
    if not API_SERVER.is_file():
        return _fail('api_server.py missing')

    api_src = API_SERVER.read_text(encoding='utf-8')
    for route in ROUTES:
        if route not in api_src:
            return _fail(f'route missing: {route!r}')

    if 'load_cached_final_confidence_report' not in api_src:
        return _fail('api_server must import load_cached_final_confidence_report')
    if 'get_final_confidence_dashboard' in api_src and 'get_final_confidence_dashboard(limit=limit)' in api_src:
        return _fail('final-confidence routes must not call live get_final_confidence_dashboard')
    if 'runtime_snapshot' in api_src.split('api_debug_final_confidence')[1].split('def api_debug_confidence_calibration')[0]:
        return _fail('final-confidence handlers must not depend on runtime snapshot')

    try:
        from backend.analytics.final_confidence_report_loader import (
            BACKEND_STAGE_44AX_FINAL_CONFIDENCE_ENDPOINT_STABLE,
            load_cached_final_confidence_report,
        )
    except Exception as exc:
        return _fail(f'loader import: {exc}')

    if not BACKEND_STAGE_44AX_FINAL_CONFIDENCE_ENDPOINT_STABLE:
        return _fail('BACKEND_STAGE_44AX_FINAL_CONFIDENCE_ENDPOINT_STABLE must be true')
    if MARKER not in LOADER.read_text(encoding='utf-8'):
        return _fail(f'{MARKER} marker missing in loader')

    t0 = time.perf_counter()
    payload = load_cached_final_confidence_report(limit=50)
    elapsed = time.perf_counter() - t0
    if elapsed > 2.0:
        return _fail(f'loader too slow: {elapsed:.2f}s')

    if REPORT_FILE.is_file():
        if payload.get('ok') is not True:
            return _fail(f'expected ok=true when report file exists: {payload.get("error")}')
        if payload.get('source') != 'data/final_confidence_report.json':
            return _fail('missing or wrong source field')
        report = payload.get('report')
        summary = payload.get('summary')
        if not isinstance(report, dict):
            return _fail('report must be dict when file exists')
        if not isinstance(summary, dict):
            return _fail('summary must be dict when file exists')
        rows = report.get('rows') if isinstance(report.get('rows'), list) else report.get('top_candidates')
        if not isinstance(rows, list):
            return _fail('report must include rows or top_candidates list')
    else:
        if payload.get('ok') is not False:
            return _fail('expected ok=false when report file missing')
        if payload.get('error') != 'final_confidence_report_missing':
            return _fail('missing file must return final_confidence_report_missing')

    print('FINAL_CONFIDENCE_ENDPOINT_STABILITY_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
