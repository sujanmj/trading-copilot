#!/usr/bin/env python3
"""Stage 50C hotfix 2 — repeated /feed keeps pending until item ingested."""

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
    print(f'FEED_REPEATED_COMMAND_KEEPS_PENDING_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    tmp = tempfile.mkdtemp()
    try:
        db_path = Path(tmp) / 'my_feed.db'
        chat_id = 'repeat_feed_chat'
        from backend.telegram.feed_pending_state import is_feed_pending, reset_feed_pending_state
        from backend.telegram.my_feed_intake import FEED_PENDING_REPLY
        from backend.telegram.telegram_analysis_bot import handle_analysis_command, handle_incoming_telegram_message

        reset_feed_pending_state()

        first = handle_analysis_command('/feed', chat_id=chat_id, dry_run=True)
        if FEED_PENDING_REPLY not in str((first[0] if first else {}).get('text') or ''):
            return _fail('/feed must open pending mode')
        if not is_feed_pending(chat_id):
            return _fail('/feed must set pending state')

        second = handle_analysis_command('/feed', chat_id=chat_id, dry_run=True)
        if FEED_PENDING_REPLY not in str((second[0] if second else {}).get('text') or ''):
            return _fail('repeated /feed must reply with pending prompt again')
        if not is_feed_pending(chat_id):
            return _fail('repeated /feed must keep pending active')

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
                    photo = {
                        'chat': {'id': chat_id},
                        'photo': [{'file_id': 'large', 'file_size': 5000}],
                    }
                    photo_results = handle_incoming_telegram_message(photo, chat_id=chat_id, dry_run=True)
            if not photo_results:
                return _fail('photo after repeated /feed must produce a response')
            photo_text = str(photo_results[0].get('text') or '')
            if 'MY_FEED_SAVED' not in photo_text:
                return _fail(f'photo after repeated /feed must save feed item, got {photo_text!r}')
            if is_feed_pending(chat_id):
                return _fail('pending must clear after successful photo ingest')
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print('FEED_REPEATED_COMMAND_KEEPS_PENDING_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
