#!/usr/bin/env python3
"""Stage 50C hotfix — build-info stage matches /status Telegram build."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _fail(msg: str) -> int:
    print(f'BUILD_INFO_STAGE_MATCHES_STATUS_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.config.local_safe_mode import ASTRAEDGE_BUILD_STAGE, ASTRAEDGE_TELEGRAM_BUILD, get_astraedge_build_stage
    from backend.telegram.response_format import format_status_text

    stage = get_astraedge_build_stage()
    if stage != '50D' or ASTRAEDGE_BUILD_STAGE != '50D':
        return _fail(f'expected build stage 50D got {stage!r}')

    status = format_status_text()
    if ASTRAEDGE_TELEGRAM_BUILD not in status:
        return _fail('/status missing Telegram build label')

    try:
        from fastapi.testclient import TestClient
        from backend.api.api_server import app

        client = TestClient(app)
        resp = client.get('/api/debug/build-info')
        if resp.status_code != 200:
            return _fail(f'build-info HTTP {resp.status_code}')
        payload = resp.json()
        if str(payload.get('stage') or '') != stage:
            return _fail(f'build-info stage {payload.get("stage")!r} != status stage {stage!r}')
    except Exception as exc:
        api_src = (PROJECT_ROOT / 'backend/api/api_server.py').read_text(encoding='utf-8')
        if 'get_astraedge_build_stage()' not in api_src:
            return _fail(f'build-info must call get_astraedge_build_stage(): {exc}')

    print('BUILD_INFO_STAGE_MATCHES_STATUS_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
