#!/usr/bin/env python3
"""Unit tests — empty My Feed GET returns 200 (Stage 50A hotfix)."""

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
    print(f'MYFEED_API_EMPTY_RETURNS_200_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        tmp = Path(tmpdir)
        db_path = tmp / 'my_feed.db'
        with patch('backend.my_feed.my_feed_db.get_my_feed_db_path', return_value=db_path):
            with patch('backend.storage.data_paths.get_data_root', return_value=tmp):
                from fastapi import FastAPI
                from fastapi.testclient import TestClient
                from backend.api.myfeed_routes import register_myfeed_routes

                app = FastAPI()
                register_myfeed_routes(app, lambda: True, lambda payload: payload)
                client = TestClient(app)
                try:
                    resp = client.get('/api/myfeed?limit=40')
                    if resp.status_code != 200:
                        return _fail(f'expected 200 got {resp.status_code}')
                    body = resp.json()
                    if body.get('ok') is not True:
                        return _fail(f'ok must be true got {body!r}')
                    if body.get('items') != []:
                        return _fail(f'expected empty items got {body.get("items")!r}')
                    if body.get('count') != 0:
                        return _fail(f'expected count=0 got {body.get("count")!r}')
                finally:
                    client.close()

    print('MYFEED_API_EMPTY_RETURNS_200_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
