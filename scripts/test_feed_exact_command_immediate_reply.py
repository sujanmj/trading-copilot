#!/usr/bin/env python3
"""Unit tests — /feed immediate pending reply (Stage 50C)."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _fail(msg: str) -> int:
    print(f'FEED_EXACT_COMMAND_IMMEDIATE_REPLY_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.telegram.feed_pending_state import is_feed_pending, reset_feed_pending_state
    from backend.telegram.my_feed_intake import FEED_PENDING_REPLY
    from backend.telegram.telegram_analysis_bot import handle_analysis_command, parse_command

    reset_feed_pending_state()
    chat_id = 'feed-exact-immediate'

    for raw in ('/feed', '/feed@AstraEdgeBot', '/feed  '):
        cmd, args = parse_command(raw)
        if cmd != 'feed' or args:
            return _fail(f'parse_command({raw!r}) => ({cmd!r}, {args!r}) expected feed with no args')

    pending_results = handle_analysis_command('/feed', chat_id=chat_id, dry_run=True)
    if not pending_results:
        return _fail('/feed must return an immediate reply')
    pending_text = str(pending_results[0].get('text') or '')
    if pending_text != FEED_PENDING_REPLY:
        return _fail(f'/feed must reply {FEED_PENDING_REPLY!r}, got {pending_text!r}')
    if not is_feed_pending(chat_id):
        return _fail('/feed must set pending My Feed input mode')

    bot_results = handle_analysis_command('/feed@AstraEdgeBot', chat_id='feed-bot-suffix', dry_run=True)
    bot_text = str(bot_results[0].get('text') or '')
    if bot_text != FEED_PENDING_REPLY:
        return _fail(f'/feed@bot must reply pending prompt, got {bot_text!r}')

    print('FEED_EXACT_COMMAND_IMMEDIATE_REPLY_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
