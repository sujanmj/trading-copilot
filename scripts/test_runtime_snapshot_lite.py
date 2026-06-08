#!/usr/bin/env python3
"""Unit tests for cache-first runtime snapshot lite (Stage 48C)."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _fail(msg: str) -> int:
    print(f'RUNTIME_SNAPSHOT_LITE_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    api_src = (PROJECT_ROOT / 'backend/api/api_server.py').read_text(encoding='utf-8')
    rm_src = (PROJECT_ROOT / 'frontend/runtime/runtimeManager.js').read_text(encoding='utf-8')

    if 'def api_market_snapshot(lite: int = Query(0))' not in api_src:
        return _fail('api_market_snapshot must accept lite query param')
    if '_compact_runtime_snapshot_lite' not in api_src:
        return _fail('missing _compact_runtime_snapshot_lite helper')
    get_block = api_src.split('def api_market_snapshot')[1].split('def _boot_runtime_snapshot_payload')[0]
    if '_build_gui_snapshot' in get_block:
        return _fail('GET snapshot must not call _build_gui_snapshot')
    if 'run_with_timeout' in get_block:
        return _fail('GET snapshot must not run_with_timeout heavy build')
    if 'cache_missing' not in api_src:
        return _fail('missing cache_missing response')
    if 'lite=1' not in rm_src:
        return _fail('runtimeManager must request lite=1 snapshot')
    if 'MAX_SNAPSHOT_RETRIES = 2' not in rm_src:
        return _fail('runtimeManager retries must be 2')
    if 'snapshotRetryDelay' not in rm_src:
        return _fail('runtimeManager missing exponential backoff')

    print('RUNTIME_SNAPSHOT_LITE_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
