#!/usr/bin/env python3
"""Unit tests — / feed typo treated as /feed (Stage 50C)."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _fail(msg: str) -> int:
    print(f'FEED_SLASH_SPACE_TYPO_SAFE_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.telegram.feed_pending_state import is_feed_pending, reset_feed_pending_state
    from backend.telegram.my_feed_intake import FEED_PENDING_REPLY, is_feed_caption
    from backend.telegram.telegram_analysis_bot import HELP_TEXT, handle_analysis_command, parse_command

    reset_feed_pending_state()
    chat_id = 'feed-slash-space-typo'

    cmd, args = parse_command('/ feed')
    if cmd != 'feed' or args:
        return _fail(f'parse_command("/ feed") => ({cmd!r}, {args!r}) expected feed with no args')

    typo_results = handle_analysis_command('/ feed', chat_id=chat_id, dry_run=True)
    typo_text = str(typo_results[0].get('text') or '')
    if typo_text != FEED_PENDING_REPLY:
        return _fail(f'/ feed must reply pending prompt, got {typo_text!r}')
    if not is_feed_pending(chat_id):
        return _fail('/ feed must set pending My Feed input mode')

    if not is_feed_caption('/ feed'):
        return _fail('is_feed_caption must accept / feed typo for photo captions')

    if '/ feed' in HELP_TEXT:
        return _fail('HELP_TEXT must not list / feed typo command')

    print('FEED_SLASH_SPACE_TYPO_SAFE_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
