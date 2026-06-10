#!/usr/bin/env python3
"""Stage 50E — Telegram media routes to My Feed before text-only router."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _fail(msg: str) -> int:
    print(f'TELEGRAM_LIVE_PHOTO_HANDLER_ROUTES_BEFORE_TEXT_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def _photo(caption: str = '/feed') -> dict:
    return {
        'chat': {'id': 'live-photo-chat'},
        'caption': caption,
        'photo': [{'file_id': 'small', 'file_size': 100}, {'file_id': 'large', 'file_size': 9000}],
    }


def main() -> int:
    bot_src = (PROJECT_ROOT / 'backend/telegram/telegram_analysis_bot.py').read_text(encoding='utf-8')
    intake_src = (PROJECT_ROOT / 'backend/telegram/my_feed_intake.py').read_text(encoding='utf-8')
    if 'route_my_feed_telegram_media_first' not in intake_src:
        return _fail('my_feed_intake missing route_my_feed_telegram_media_first')
    if 'route_my_feed_telegram_media_first' not in bot_src:
        return _fail('handle_incoming must call route_my_feed_telegram_media_first before text router')
    if 'Media-first' not in bot_src:
        return _fail('handle_incoming missing media-first comment/block')

    call_order: list[str] = []

    def _media_first(*args, **kwargs):
        call_order.append('media_first')
        return 'MY_FEED_SAVED\nitems_found=1'

    def _handle_message(*args, **kwargs):
        call_order.append('text_router')
        return []

    from backend.telegram import telegram_analysis_bot

    with patch('backend.telegram.my_feed_intake.route_my_feed_telegram_media_first', side_effect=_media_first):
        with patch.object(telegram_analysis_bot, 'handle_message', side_effect=_handle_message):
            results = telegram_analysis_bot.handle_incoming_telegram_message(_photo('/feed'), dry_run=True)
    if call_order != ['media_first']:
        return _fail(f'expected media_first before text router, got {call_order!r}')
    if not results or 'MY_FEED_SAVED' not in str(results[0].get('text') or ''):
        return _fail('media-first route must return MY_FEED_SAVED reply payload')

    listen_src = bot_src
    if 'handle_incoming_telegram_message' not in listen_src or 'has_media' not in listen_src:
        return _fail('listen_forever must dispatch media through handle_incoming_telegram_message')

    print('TELEGRAM_LIVE_PHOTO_HANDLER_ROUTES_BEFORE_TEXT_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
