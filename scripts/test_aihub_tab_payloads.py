#!/usr/bin/env python3
"""
Offline/module tests for AI Hub tab payloads (Stage 44AQ).

Prints exactly AIHUB_TAB_PAYLOADS_TEST_OK on success.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

MAX_TAB_SECONDS = 12.0
API_TABS = (
    'brain', 'govt', 'scan', 'market', 'global', 'news', 'tv', 'calib', 'journal',
)


def _fail(msg: str) -> int:
    print(f'AIHUB_TAB_PAYLOADS_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.analytics.aihub_tab_payloads import build_aihub_tab_payload, build_scan_payload

    started = time.perf_counter()
    for tab in API_TABS:
        t0 = time.perf_counter()
        payload = build_aihub_tab_payload(tab)
        elapsed = time.perf_counter() - t0
        if elapsed > MAX_TAB_SECONDS:
            return _fail(f'tab {tab!r} took {elapsed:.1f}s (max {MAX_TAB_SECONDS}s)')
        if payload.get('ok') is not True:
            return _fail(f'tab {tab!r} returned ok={payload.get("ok")!r}')

    scan = build_scan_payload()
    memory_rows = [r for r in scan.get('items') or [] if r.get('is_memory_fallback')]
    if memory_rows:
        sample = memory_rows[0]
        if sample.get('price') is not None:
            return _fail('memory fallback row must have price=null')
        if sample.get('change_pct') is not None:
            return _fail('memory fallback row must have change_pct=null')
        if sample.get('source') != 'market-memory':
            return _fail('memory fallback row must have source=market-memory')

    total = time.perf_counter() - started
    if total > MAX_TAB_SECONDS * len(API_TABS):
        return _fail(f'all tabs took {total:.1f}s — too slow')

    print('AIHUB_TAB_PAYLOADS_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
