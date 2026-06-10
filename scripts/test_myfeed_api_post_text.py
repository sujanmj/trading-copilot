#!/usr/bin/env python3
"""Unit tests — POST /api/myfeed stores text (Stage 50A hotfix)."""

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
    print(f'MYFEED_API_POST_TEXT_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    market_text = 'NIFTY gains on strong FII inflows and banking sector rally today'
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
                    post = client.post('/api/myfeed', json={'text': market_text, 'source': 'gui_text'})
                    if post.status_code != 200:
                        return _fail(f'POST expected 200 got {post.status_code} {post.text[:200]}')
                    body = post.json()
                    if body.get('ok') is not True or body.get('saved') is not True:
                        return _fail(f'POST must save text got {body!r}')
                    if not body.get('feed_id'):
                        return _fail('POST must return feed_id')
                    item = body.get('item') or {}
                    if 'image_path' in item:
                        return _fail('item must not include image_path')

                    listing = client.get('/api/myfeed?limit=40')
                    listed = listing.json()
                    if listed.get('count', 0) < 1:
                        return _fail('GET must return stored item')

                    from backend.my_feed.feed_processor import ingest_text

                    tg = ingest_text('RBI keeps repo rate unchanged; banking stocks in focus', source='telegram_text')
                    if not tg.get('ok'):
                        return _fail('Telegram ingest must use same store')
                    listed2 = client.get('/api/myfeed?limit=40').json()
                    if listed2.get('count', 0) < 2:
                        return _fail('Telegram and GUI must share canonical store')
                finally:
                    client.close()

    print('MYFEED_API_POST_TEXT_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
