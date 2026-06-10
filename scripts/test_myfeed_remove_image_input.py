#!/usr/bin/env python3
"""Stage 50G — image input removed from My Feed."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _fail(msg: str) -> int:
    print(f'MYFEED_REMOVE_IMAGE_INPUT_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def _photo() -> dict:
    return {
        'chat': {'id': 'text-only-chat'},
        'photo': [{'file_id': 'large', 'file_size': 5000}],
    }


def main() -> int:
    from backend.telegram.my_feed_intake import FEED_TEXT_ONLY_IMAGE_REPLY
    from backend.telegram.telegram_analysis_bot import handle_incoming_telegram_message

    intake_src = (PROJECT_ROOT / 'backend/telegram/my_feed_intake.py').read_text(encoding='utf-8')
    if 'route_my_feed_telegram_media_first' in intake_src:
        return _fail('my_feed_intake must not route photo OCR')
    if 'extract_market_text_from_image_temp' in intake_src:
        return _fail('my_feed_intake must not call image OCR')

    bot_src = (PROJECT_ROOT / 'backend/telegram/telegram_analysis_bot.py').read_text(encoding='utf-8')
    if 'set_feed_pending' in bot_src:
        return _fail('feed pending screenshot mode must be removed')

    routes_src = (PROJECT_ROOT / 'backend/api/myfeed_routes.py').read_text(encoding='utf-8')
    if 'ingest_screenshot_bytes' in routes_src:
        return _fail('screenshot API must not ingest images')

    results = handle_incoming_telegram_message(_photo(), dry_run=True)
    if not results:
        return _fail('photo message must produce a reply')
    reply = str(results[0].get('text') or '')
    if FEED_TEXT_ONLY_IMAGE_REPLY not in reply and 'text-only now' not in reply.lower():
        return _fail(f'photo must get text-only rejection, got {reply!r}')

    print('MYFEED_REMOVE_IMAGE_INPUT_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
