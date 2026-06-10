#!/usr/bin/env python3
"""Unit tests — pending mode must not store slash commands as feed (Stage 50C)."""

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
    print(f'FEED_PENDING_DOES_NOT_STORE_COMMANDS_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    tmp = tempfile.mkdtemp()
    try:
        db_path = Path(tmp) / 'my_feed.db'
        with patch('backend.my_feed.my_feed_db.get_my_feed_db_path', return_value=db_path):
            from backend.my_feed.feed_processor import list_feed_items
            from backend.telegram.feed_pending_state import is_feed_pending, reset_feed_pending_state
            from backend.telegram.my_feed_intake import FEED_PENDING_REPLY
            from backend.telegram.telegram_analysis_bot import handle_analysis_command, handle_incoming_telegram_message

            reset_feed_pending_state()
            chat_id = 'feed-pending-no-cmd'

            handle_analysis_command('/feed', chat_id=chat_id, dry_run=True)
            if not is_feed_pending(chat_id):
                return _fail('/feed must enter pending mode')

            status_results = handle_incoming_telegram_message(
                {'chat': {'id': chat_id}, 'text': '/status'},
                dry_run=True,
            )
            if not status_results:
                return _fail('/status during pending must run status command')
            status_text = str(status_results[0].get('text') or '')
            if 'Telegram build' not in status_text and 'status' not in status_text.lower():
                return _fail(f'/status during pending must not ingest feed text: {status_text!r}')
            if list_feed_items(limit=10):
                return _fail('/status during pending must not create feed item')

            feed_typo = handle_incoming_telegram_message(
                {'chat': {'id': chat_id}, 'text': '/ feed'},
                dry_run=True,
            )
            typo_text = str(feed_typo[0].get('text') or '')
            if typo_text != FEED_PENDING_REPLY:
                return _fail(f'/ feed during pending must be treated as /feed, got {typo_text!r}')
            if list_feed_items(limit=10):
                return _fail('/ feed during pending must not create feed item')

            handle_analysis_command('/feed', chat_id=chat_id, dry_run=True)
            photo_results = handle_incoming_telegram_message(
                {
                    'chat': {'id': chat_id},
                    'photo': [{'file_id': 'dry-photo', 'file_size': 1000}],
                },
                dry_run=True,
            )
            if not photo_results:
                return _fail('pending screenshot must be ingested without caption')
            photo_text = str(photo_results[0].get('text') or '')
            if 'MY_FEED_SAVED' not in photo_text:
                return _fail(f'pending screenshot ingest failed: {photo_text!r}')
            if is_feed_pending(chat_id):
                return _fail('pending state must clear after screenshot ingest')
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print('FEED_PENDING_DOES_NOT_STORE_COMMANDS_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
