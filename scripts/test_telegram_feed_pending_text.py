#!/usr/bin/env python3
"""Unit tests — /feed pending text intake (Stage 50B final)."""

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
    print(f'TELEGRAM_FEED_PENDING_TEXT_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    tmp = tempfile.mkdtemp()
    try:
        db_path = Path(tmp) / 'my_feed.db'
        with patch('backend.my_feed.my_feed_db.get_my_feed_db_path', return_value=db_path):
            from backend.telegram.feed_pending_state import is_feed_pending, reset_feed_pending_state
            from backend.telegram.my_feed_intake import FEED_PENDING_REPLY
            from backend.telegram.telegram_analysis_bot import handle_analysis_command, handle_incoming_telegram_message

            reset_feed_pending_state()
            chat_id = 'pending-text-chat'

            pending_results = handle_analysis_command('/feed', chat_id=chat_id, dry_run=True)
            if not pending_results:
                return _fail('/feed must return pending reply')
            pending_text = str(pending_results[0].get('text') or '')
            if FEED_PENDING_REPLY not in pending_text:
                return _fail(f'/feed alone must reply pending prompt, got {pending_text!r}')
            if not is_feed_pending(chat_id):
                return _fail('/feed must set pending state for chat')

            follow_up = {
                'chat': {'id': chat_id},
                'text': 'RBI cuts repo rate today on inflation outlook',
            }
            ingest_results = handle_incoming_telegram_message(follow_up, dry_run=True)
            if not ingest_results:
                return _fail('pending follow-up text must be ingested')
            ingest_text = str(ingest_results[0].get('text') or '')
            if 'MY_FEED_SAVED' not in ingest_text:
                return _fail(f'pending text ingest failed: {ingest_text!r}')
            if is_feed_pending(chat_id):
                return _fail('pending state must clear after one ingest')

            direct = handle_analysis_command(
                '/feed INFY upgrade on strong quarterly results today',
                chat_id=chat_id,
                dry_run=True,
            )
            direct_text = str(direct[0].get('text') or '')
            if 'MY_FEED_SAVED' not in direct_text:
                return _fail(f'/feed <text> direct ingest failed: {direct_text!r}')
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print('TELEGRAM_FEED_PENDING_TEXT_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
