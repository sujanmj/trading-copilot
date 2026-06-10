#!/usr/bin/env python3
"""Stage 50E — pending /feed then photo routes through live media handler."""

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
    print(f'TELEGRAM_FEED_PHOTO_PENDING_LIVE_SHAPE_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def _photo(chat_id: str) -> dict:
    return {
        'chat': {'id': chat_id},
        'photo': [{'file_id': 'large', 'file_size': 8000}],
    }


def main() -> int:
    tmp = tempfile.mkdtemp()
    try:
        db_path = Path(tmp) / 'my_feed.db'
        chat_id = 'pending-live-chat'
        from backend.telegram.feed_pending_state import reset_feed_pending_state, set_feed_pending
        from backend.telegram.telegram_analysis_bot import handle_incoming_telegram_message

        reset_feed_pending_state()
        set_feed_pending(chat_id)

        with patch('backend.my_feed.my_feed_db.get_my_feed_db_path', return_value=db_path):
            with patch('backend.telegram.my_feed_intake.download_telegram_file', return_value=b'\x89PNGfake'):
                with patch(
                    'backend.my_feed.image_extraction.extract_market_text_from_image_temp',
                    return_value={
                        'ok': True,
                        'text': 'INDmoney: CHAMBLFERT surges 5.3%',
                        'notifications': ['INDmoney: CHAMBLFERT surges 5.3%'],
                        'ignored_private_count': 0,
                        'needs_text': False,
                    },
                ):
                    results = handle_incoming_telegram_message(_photo(chat_id), chat_id=chat_id, dry_run=False)
        if not results:
            return _fail('pending photo must produce Telegram response list')
        text = str(results[0].get('text') or '')
        if 'MY_FEED_SAVED' not in text:
            return _fail(f'pending photo must reply MY_FEED_SAVED, got {text!r}')
        if 'CHAMBLFERT' not in text:
            return _fail('CHAMBLFERT notification must surface entity/ticker in reply')
        if 'WATCH FOR CONFIRMATION' not in text:
            return _fail('CHAMBLFERT surge must classify as WATCH FOR CONFIRMATION')
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print('TELEGRAM_FEED_PHOTO_PENDING_LIVE_SHAPE_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
