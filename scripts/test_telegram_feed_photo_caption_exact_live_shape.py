#!/usr/bin/env python3
"""Stage 50E — caption /feed exact shapes route to My Feed photo handler."""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _fail(msg: str) -> int:
    print(f'TELEGRAM_FEED_PHOTO_CAPTION_EXACT_LIVE_SHAPE_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def _photo(caption: str) -> dict:
    return {
        'chat': {'id': 'caption-shape-chat'},
        'caption': caption,
        'photo': [{'file_id': 'large', 'file_size': 5000}],
    }


def _doc_image(caption: str) -> dict:
    return {
        'chat': {'id': 'caption-shape-chat'},
        'caption': caption,
        'document': {'file_id': 'doc-img', 'mime_type': 'image/png', 'file_name': 'screen.png'},
    }


def main() -> int:
    from backend.telegram.my_feed_intake import is_feed_caption, is_feed_caption_only, should_process_feed_photo

    for caption in ('/feed', '/feed ', '/ feed', '/feed@MyBot'):
        if not is_feed_caption(caption) and not is_feed_caption_only(caption):
            return _fail(f'caption {caption!r} must be treated as feed caption')
        if not should_process_feed_photo(_photo(caption), 'caption-shape-chat'):
            return _fail(f'photo with caption {caption!r} must route to feed handler')

    if not should_process_feed_photo(_doc_image('/feed'), 'caption-shape-chat'):
        return _fail('image document with /feed caption must route to feed handler')

    tmp = tempfile.mkdtemp()
    try:
        db_path = Path(tmp) / 'my_feed.db'
        with patch('backend.my_feed.my_feed_db.get_my_feed_db_path', return_value=db_path):
            with patch('backend.telegram.my_feed_intake.download_telegram_file', return_value=b'\x89PNGfake'):
                with patch(
                    'backend.my_feed.image_extraction.extract_market_text_from_image_temp',
                    return_value={
                        'ok': True,
                        'text': 'Inshorts: Iran attacks US bases in Kuwait, Jordan, Bahrain',
                        'notifications': ['Inshorts: Iran attacks US bases in Kuwait, Jordan, Bahrain'],
                        'ignored_private_count': 0,
                        'needs_text': False,
                    },
                ):
                    from backend.telegram.my_feed_intake import route_my_feed_telegram_media_first

                    reply = route_my_feed_telegram_media_first(_photo('/feed '), dry_run=False)
        if not reply or 'MY_FEED_SAVED' not in reply:
            return _fail(f'/feed whitespace caption must save, got {reply!r}')
        if 'MARKET RISK ALERT' not in reply:
            return _fail('Iran geopolitical alert must classify as MARKET RISK ALERT')
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print('TELEGRAM_FEED_PHOTO_CAPTION_EXACT_LIVE_SHAPE_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
