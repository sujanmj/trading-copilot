#!/usr/bin/env python3
"""Unit tests — GUI My Feed screenshot API contract (Stage 50B)."""

from __future__ import annotations

import io
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
import os

os.chdir(PROJECT_ROOT)

CONTRACT_KEYS = frozenset({
    'ok', 'saved', 'feed_id', 'item', 'reply', 'source', 'data_root',
})


def _fail(msg: str) -> int:
    print(f'GUI_MYFEED_SCREENSHOT_API_CONTRACT_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def _build_client(tmp: Path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend.api.myfeed_routes import register_myfeed_routes

    app = FastAPI()
    register_myfeed_routes(app, lambda: True, lambda payload: payload)
    return TestClient(app)


def main() -> int:
    routes_src = (PROJECT_ROOT / 'backend/api/myfeed_routes.py').read_text(encoding='utf-8')
    if "'/api/myfeed/screenshot'" not in routes_src:
        return _fail('myfeed_routes must register POST /api/myfeed/screenshot')

    fake_ocr = {
        'ok': True,
        'text': 'NIFTY surges on strong FII inflows across banking sector today',
        'cleaned_summary': 'NIFTY surges on strong FII inflows across banking sector today',
        'confidence': 0.85,
        'extracted': {},
        'error': '',
    }

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        tmp = Path(tmpdir)
        db_path = tmp / 'my_feed.db'
        with patch('backend.my_feed.my_feed_db.get_my_feed_db_path', return_value=db_path):
            with patch('backend.storage.data_paths.get_data_root', return_value=tmp):
                with patch('backend.my_feed.image_extraction.extract_market_text_from_image_bytes', return_value=fake_ocr):
                    client = _build_client(tmp)
                    try:
                        text_resp = client.post(
                            '/api/myfeed',
                            json={'text': 'RELIANCE results beat estimates on strong revenue growth', 'source': 'gui_text'},
                        )
                        shot_resp = client.post(
                            '/api/myfeed/screenshot',
                            files={'file': ('screen.png', io.BytesIO(b'\x89PNGfake'), 'image/png')},
                        )
                    finally:
                        client.close()

        if text_resp.status_code != 200:
            return _fail(f'POST /api/myfeed expected 200 got {text_resp.status_code}')
        if shot_resp.status_code != 200:
            return _fail(f'POST /api/myfeed/screenshot expected 200 got {shot_resp.status_code}')

        text_body = text_resp.json()
        shot_body = shot_resp.json()
        for label, body in (('text', text_body), ('screenshot', shot_body)):
            missing = CONTRACT_KEYS - set(body.keys())
            if missing:
                return _fail(f'POST /api/myfeed ({label}) missing keys {sorted(missing)}')
            if body.get('source') != 'canonical_user_feed':
                return _fail(f'{label} response missing canonical source')
            if not str(body.get('data_root') or '').strip():
                return _fail(f'{label} response missing data_root')
            if body.get('ok') is not True:
                return _fail(f'{label} response ok must be true got {body!r}')
            if not body.get('saved'):
                return _fail(f'{label} response must save feed item')
            item = body.get('item') or {}
            if not item.get('feed_id'):
                return _fail(f'{label} response item missing feed_id')

        allowed_optional = frozenset({'duplicate'})
        extra_shot = set(shot_body.keys()) - CONTRACT_KEYS - allowed_optional
        if extra_shot:
            return _fail(f'screenshot response has unexpected keys {sorted(extra_shot)}')
        extra_text = set(text_body.keys()) - CONTRACT_KEYS - allowed_optional
        if extra_text:
            return _fail(f'text response has unexpected keys {sorted(extra_text)}')
        if set(text_body.keys()) != set(shot_body.keys()):
            extra_text = set(text_body.keys()) - set(shot_body.keys())
            extra_shot = set(shot_body.keys()) - set(text_body.keys())
            return _fail(
                f'screenshot vs text response key mismatch extra_text={sorted(extra_text)} extra_shot={sorted(extra_shot)}'
            )

    print('GUI_MYFEED_SCREENSHOT_API_CONTRACT_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
