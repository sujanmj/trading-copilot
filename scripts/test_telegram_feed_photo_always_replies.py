#!/usr/bin/env python3
"""Stage 50E — Telegram feed photos always reply MY_FEED_* never silent."""

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
    print(f'TELEGRAM_FEED_PHOTO_ALWAYS_REPLIES_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def _photo(caption: str = '/feed') -> dict:
    return {
        'chat': {'id': 'always-reply-chat'},
        'caption': caption,
        'photo': [{'file_id': 'large', 'file_size': 7000}],
    }


def main() -> int:
    intake_src = (PROJECT_ROOT / 'backend/telegram/my_feed_intake.py').read_text(encoding='utf-8')
    for tag in (
        'MYFEED_PHOTO_RECEIVED',
        'MYFEED_PHOTO_DOWNLOAD_OK',
        'MYFEED_PHOTO_OCR_OK',
        'MYFEED_PHOTO_OCR_FAIL',
        'MYFEED_PHOTO_TEMP_DELETED',
        'MYFEED_PHOTO_REPLY_SENT',
    ):
        if tag not in intake_src:
            return _fail(f'missing safe log tag {tag}')

    tmp = tempfile.mkdtemp()
    try:
        from backend.telegram.telegram_analysis_bot import handle_incoming_telegram_message

        with patch('backend.telegram.my_feed_intake.download_telegram_file', return_value=b''):
            fail_results = handle_incoming_telegram_message(_photo('/feed'), dry_run=False)
        if not fail_results:
            return _fail('download failure must not be silent')
        fail_text = str(fail_results[0].get('text') or '')
        if 'MY_FEED_NEEDS_TEXT' not in fail_text:
            return _fail(f'download failure must reply MY_FEED_NEEDS_TEXT, got {fail_text!r}')

        db_path = Path(tmp) / 'my_feed.db'
        with patch('backend.my_feed.my_feed_db.get_my_feed_db_path', return_value=db_path):
            with patch('backend.telegram.my_feed_intake.download_telegram_file', return_value=b'\x89PNGfake'):
                with patch(
                    'backend.my_feed.image_extraction.extract_market_text_from_image_temp',
                    return_value={'ok': False, 'needs_text': True, 'text': '', 'notifications': []},
                ):
                    ocr_fail = handle_incoming_telegram_message(_photo('/feed'), dry_run=False)
        if not ocr_fail:
            return _fail('OCR failure must not be silent')
        ocr_text = str(ocr_fail[0].get('text') or '')
        if 'MY_FEED_NEEDS_TEXT' not in ocr_text:
            return _fail(f'OCR failure must reply MY_FEED_NEEDS_TEXT, got {ocr_text!r}')

        listen_src = (PROJECT_ROOT / 'backend/telegram/telegram_analysis_bot.py').read_text(encoding='utf-8')
        if 'is_feed_media' not in listen_src or 'handle_feed_photo_or_fail' not in listen_src:
            return _fail('listen_forever must include feed media fallback reply path')
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print('TELEGRAM_FEED_PHOTO_ALWAYS_REPLIES_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
