#!/usr/bin/env python3
"""Stage 50F — vision path must not persist image/base64/path/filename."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _fail(msg: str) -> int:
    print(f'MYFEED_VISION_NO_IMAGE_PERSISTENCE_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    groq_src = (PROJECT_ROOT / 'backend/my_feed/groq_vision_fallback.py').read_text(encoding='utf-8')
    if 'base64' in groq_src and 'safe_print' in groq_src and groq_src.find('base64') < groq_src.find('safe_print'):
        pass
    if 'write(' in groq_src and 'image' in groq_src.lower():
        return _fail('groq vision module must not write image files')

    extraction_src = (PROJECT_ROOT / 'backend/my_feed/image_extraction.py').read_text(encoding='utf-8')
    if 'finally' not in extraction_src or 'os.remove' not in extraction_src:
        return _fail('image_extraction must delete temp files in finally')

    schema = (PROJECT_ROOT / 'backend/my_feed/my_feed_db.py').read_text(encoding='utf-8')
    schema_block = schema.split('SCHEMA = """', 1)[1].split('"""', 1)[0].lower()
    for col in ('image_path', 'base64', 'filename'):
        if col in schema_block:
            return _fail(f'my_feed schema must not define storage column {col!r}')

    inserted: list[dict] = []

    def _track_insert(payload):
        inserted.append(dict(payload))
        payload = dict(payload)
        payload['feed_id'] = f'feed_{len(inserted)}'
        payload['created_at'] = '2026-01-01T00:00:00Z'
        return payload

    tmp = tempfile.mkdtemp()
    try:
        db_path = Path(tmp) / 'my_feed.db'
        vision_items = [{
            'cleaned_summary': 'CHAMBLFERT surges 5.3%',
            'raw_market_text': 'CHAMBLFERT surges 5.3%',
            'tickers': ['CHAMBLFERT'],
            'entities': ['CHAMBLFERT'],
            'suggested_action': 'WATCH FOR CONFIRMATION',
            'impact_score': 72,
            'urgency': 'high',
        }]
        with patch('backend.my_feed.my_feed_db.get_my_feed_db_path', return_value=db_path):
            with patch('backend.my_feed.my_feed_db.insert_feed_item', side_effect=_track_insert):
                from backend.my_feed.feed_processor import ingest_vision_items

                ingest_vision_items(vision_items, source='telegram_screenshot')
        if not inserted:
            return _fail('vision ingest must save text records')
        for row in inserted:
            blob = str(row).lower()
            for forbidden in ('image_path', 'base64', 'filename', 'data:image'):
                if forbidden in blob:
                    return _fail(f'feed record must not contain {forbidden!r}')
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)

    print('MYFEED_VISION_NO_IMAGE_PERSISTENCE_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
