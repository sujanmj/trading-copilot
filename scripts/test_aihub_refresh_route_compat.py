#!/usr/bin/env python3
"""Unit tests for AIHub refresh route GET+POST compat (Stage 48D)."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _fail(msg: str) -> int:
    print(f'AIHUB_REFRESH_ROUTE_COMPAT_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    api_src = (PROJECT_ROOT / 'backend/api/api_server.py').read_text(encoding='utf-8')
    idx = (PROJECT_ROOT / 'frontend/index.html').read_text(encoding='utf-8')

    block = api_src.split('def api_debug_aihub_tab_refresh')[0]
    if '@app.get("/api/debug/aihub-tab/{tab}/refresh"' not in api_src:
        return _fail('GET refresh route missing')
    if '@app.post("/api/debug/aihub-tab/{tab}/refresh"' not in api_src:
        return _fail('POST refresh route missing')
    if 'method: \'POST\'' not in idx and 'method: "POST"' not in idx:
        return _fail('frontend refresh must use POST')
    if 'AI Hub refresh route unavailable' not in idx:
        return _fail('missing refresh unavailable message')

    print('AIHUB_REFRESH_ROUTE_COMPAT_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
