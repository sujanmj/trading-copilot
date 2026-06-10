#!/usr/bin/env python3
"""Unit tests — /feed pending photo OCR intake (Stage 50B final)."""

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
    print(f'TELEGRAM_FEED_PENDING_PHOTO_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def _photo_message(chat_id: str) -> dict:
    return {
        'chat': {'id': chat_id},
        'photo': [
            {'file_id': 'small', 'file_size': 100},
            {'file_id': 'large', 'file_size': 5000},
        ],
    }


def main() -> int:
    tmp = tempfile.mkdtemp()
    try:
        db_path = Path(tmp) / 'my_feed.db'
        with patch('backend.my_feed.my_feed_db.get_my_feed_db_path', return_value=db_path):
            from backend.telegram.feed_pending_state import is_feed_pending, reset_feed_pending_state, set_feed_pending
            from backend.telegram.telegram_analysis_bot import handle_incoming_telegram_message

            reset_feed_pending_state()
            chat_id = 'pending-photo-chat'
            set_feed_pending(chat_id)

            with patch(
                'backend.telegram.my_feed_intake.download_telegram_file',
                return_value=b'\x89PNGfake',
            ):
                with patch(
                    'backend.my_feed.image_extraction.extract_market_text_from_image_bytes',
                    return_value={
                        'ok': True,
                        'text': 'NIFTY gains on banking sector rally today',
                        'cleaned_summary': 'NIFTY gains on banking sector rally today',
                        'confidence': 0.85,
                        'extracted': {},
                        'error': '',
                    },
                ):
                    results = handle_incoming_telegram_message(_photo_message(chat_id), dry_run=False)

            if not results:
                return _fail('pending photo must produce feed reply')
            reply = str(results[0].get('text') or '')
            if 'MY_FEED_SAVED' not in reply:
                return _fail(f'pending photo OCR ingest failed: {reply!r}')
            if is_feed_pending(chat_id):
                return _fail('pending state must clear after photo ingest')

            ignored = handle_incoming_telegram_message(_photo_message('other-chat'), dry_run=True)
            if ignored:
                return _fail('photo without pending or /feed caption must be ignored')
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print('TELEGRAM_FEED_PENDING_PHOTO_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
