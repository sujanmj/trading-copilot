#!/usr/bin/env python3
"""Unit tests — My Feed API routes (Stage 50A hotfix)."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)


def _fail(msg: str) -> int:
    print(f'MYFEED_API_ROUTES_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def _build_client(tmp: Path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend.api.myfeed_routes import register_myfeed_routes

    app = FastAPI()

    def _auth_ok():
        return True

    register_myfeed_routes(app, _auth_ok, lambda payload: payload)
    return TestClient(app)


def main() -> int:
    api_src = (PROJECT_ROOT / 'backend/api/api_server.py').read_text(encoding='utf-8')
    routes_src = (PROJECT_ROOT / 'backend/api/myfeed_routes.py').read_text(encoding='utf-8')
    req_src = (PROJECT_ROOT / 'requirements.txt').read_text(encoding='utf-8')
    if 'python-multipart' not in req_src:
        return _fail('requirements.txt must include python-multipart for UploadFile routes')
    if 'register_myfeed_routes' not in api_src:
        return _fail('api_server must call register_myfeed_routes')
    for needle in (
        "'/api/myfeed'",
        "'/api/myfeed/today'",
        "'/api/myfeed/scan'",
        "'/api/myfeed/archive/{feed_id}'",
        "'/api/myfeed/text'",
        'canonical_user_feed',
        'data_root',
    ):
        if needle not in routes_src:
            return _fail(f'myfeed_routes missing {needle!r}')

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        tmp = Path(tmpdir)
        db_path = tmp / 'my_feed.db'
        with patch('backend.my_feed.my_feed_db.get_my_feed_db_path', return_value=db_path):
            with patch('backend.storage.data_paths.get_data_root', return_value=tmp):
                client = _build_client(tmp)
                try:
                    for path in (
                        '/api/myfeed?limit=40',
                        '/api/myfeed/today',
                        '/api/myfeed/scan',
                    ):
                        resp = client.get(path)
                        if resp.status_code != 200:
                            return _fail(f'{path} expected 200 got {resp.status_code}')
                        body = resp.json()
                        if body.get('ok') is not True:
                            return _fail(f'{path} ok must be true got {body!r}')
                        if body.get('source') != 'canonical_user_feed':
                            return _fail(f'{path} missing canonical source')
                        if not str(body.get('data_root') or '').strip():
                            return _fail(f'{path} missing data_root')
                finally:
                    client.close()

    print('MYFEED_API_ROUTES_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
