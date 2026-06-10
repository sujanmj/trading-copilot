#!/usr/bin/env python3
"""Unit tests — Telegram photo+caption /feed intake (Stage 50B final)."""

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
    print(f'TELEGRAM_FEED_CAPTION_PHOTO_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def _photo_message(caption: str) -> dict:
    return {
        'chat': {'id': 'caption-photo-chat'},
        'caption': caption,
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
            from backend.telegram.my_feed_intake import handle_telegram_feed_message, process_feed_message
            from backend.telegram.telegram_analysis_bot import handle_incoming_telegram_message

            reply = handle_telegram_feed_message(_photo_message('/feed'), dry_run=True)
            if not reply or 'MY_FEED_SAVED' not in reply:
                return _fail(f'dry_run photo /feed must route to My Feed intake, got {reply!r}')

            caption_reply = handle_telegram_feed_message(
                _photo_message('/feed NIFTY futures rise on strong FII inflows today'),
                dry_run=True,
            )
            if not caption_reply or 'MY_FEED_SAVED' not in caption_reply:
                return _fail(f'caption text merge failed: {caption_reply!r}')

            ingest_calls: list[dict] = []

            def _track_ingest(**kwargs):
                ingest_calls.append(kwargs)
                from backend.my_feed.feed_processor import ingest_text

                return ingest_text(
                    kwargs.get('text') or 'NIFTY gains on banking sector rally today',
                    source=kwargs.get('source') or 'telegram_screenshot',
                )

            with patch('backend.telegram.my_feed_intake.ingest_telegram_feed', side_effect=_track_ingest):
                with patch(
                    'backend.telegram.my_feed_intake.download_telegram_file',
                    return_value=b'\x89PNGfake',
                ):
                    live_reply = process_feed_message(_photo_message('/feed'), dry_run=False)

            if not ingest_calls:
                return _fail('photo /feed must call ingest_telegram_feed')
            if ingest_calls[0].get('image_bytes') != b'\x89PNGfake':
                return _fail('photo /feed must pass downloaded image bytes to intake')
            if not live_reply or 'MY_FEED_SAVED' not in live_reply:
                return _fail(f'live photo /feed reply missing MY_FEED_SAVED: {live_reply!r}')

            update_results = handle_incoming_telegram_message(_photo_message('/feed'), dry_run=True)
            if not update_results:
                return _fail('handle_incoming_telegram_message must return feed reply for photo caption')
            update_text = str(update_results[0].get('text') or '')
            if 'MY_FEED_SAVED' not in update_text:
                return _fail(f'update route failed for /feed photo: {update_text!r}')
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print('TELEGRAM_FEED_CAPTION_PHOTO_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
