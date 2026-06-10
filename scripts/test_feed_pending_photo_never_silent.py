#!/usr/bin/env python3
"""Stage 50C hotfix 2 — pending photo must always reply MY_FEED_*."""

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
    print(f'FEED_PENDING_PHOTO_NEVER_SILENT_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def _photo(chat_id: str) -> dict:
    return {
        'chat': {'id': chat_id},
        'photo': [{'file_id': 'small', 'file_size': 100}, {'file_id': 'large', 'file_size': 9000}],
    }


def main() -> int:
    tmp = tempfile.mkdtemp()
    try:
        db_path = Path(tmp) / 'my_feed.db'
        chat_id = 'pending_photo_chat'
        from backend.telegram.feed_pending_state import reset_feed_pending_state, set_feed_pending
        from backend.telegram.telegram_analysis_bot import handle_incoming_telegram_message

        reset_feed_pending_state()
        set_feed_pending(chat_id)

        with patch('backend.my_feed.my_feed_db.get_my_feed_db_path', return_value=db_path):
            with patch('backend.telegram.my_feed_intake.download_telegram_file', return_value=b'\x89PNGfake'):
                with patch(
                    'backend.my_feed.image_extraction.extract_market_text_from_image_bytes',
                    return_value={
                        'ok': True,
                        'text': 'NIFTY opens higher on strong global cues across banking sector today',
                        'cleaned_summary': 'NIFTY opens higher on strong global cues across banking sector today',
                        'confidence': 0.85,
                        'extracted': {},
                        'error': '',
                    },
                ):
                    ok_results = handle_incoming_telegram_message(_photo(chat_id), chat_id=chat_id, dry_run=True)
            if not ok_results:
                return _fail('pending photo must produce a Telegram response')
            ok_text = str(ok_results[0].get('text') or '')
            if 'MY_FEED_SAVED' not in ok_text:
                return _fail(f'pending photo OCR success must reply MY_FEED_SAVED, got {ok_text!r}')

            reset_feed_pending_state()
            set_feed_pending(chat_id)
            with patch('backend.telegram.my_feed_intake.download_telegram_file', return_value=b''):
                fail_results = handle_incoming_telegram_message(_photo(chat_id), chat_id=chat_id, dry_run=True)
            if not fail_results:
                return _fail('download failure must still produce a Telegram response')
            fail_text = str(fail_results[0].get('text') or '')
            if 'MY_FEED_NEEDS_TEXT' not in fail_text:
                return _fail(f'download failure must reply MY_FEED_NEEDS_TEXT, got {fail_text!r}')

            reset_feed_pending_state()
            set_feed_pending(chat_id)
            with patch('backend.telegram.my_feed_intake.download_telegram_file', return_value=b'\x89PNGfake'):
                with patch(
                    'backend.my_feed.image_extraction.extract_market_text_from_image_bytes',
                    return_value={'ok': False, 'text': '', 'error': 'tesseract_unavailable', 'extracted': {}},
                ):
                    ocr_fail = handle_incoming_telegram_message(_photo(chat_id), chat_id=chat_id, dry_run=False)
            if not ocr_fail:
                return _fail('OCR failure must still produce a Telegram response')
            ocr_text = str(ocr_fail[0].get('text') or '')
            if 'MY_FEED_NEEDS_TEXT' not in ocr_text:
                return _fail(f'OCR failure must reply MY_FEED_NEEDS_TEXT, got {ocr_text!r}')

            extraction = (PROJECT_ROOT / 'backend/my_feed/image_extraction.py').read_text(encoding='utf-8')
            if 'os.remove' not in extraction or 'finally' not in extraction:
                return _fail('image_extraction must delete temp image in finally block')
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print('FEED_PENDING_PHOTO_NEVER_SILENT_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
