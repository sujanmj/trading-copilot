#!/usr/bin/env python3
"""Unit tests — single /feed command only (Stage 50B final)."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _fail(msg: str) -> int:
    print(f'TELEGRAM_FEED_SINGLE_COMMAND_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.telegram.my_feed_intake import FEED_PENDING_REPLY, is_feed_caption
    from backend.telegram.telegram_analysis_bot import HELP_TEXT, parse_command

    for raw, expected_cmd, expected_args in (
        ('/feed', 'feed', ''),
        ('/feed RBI cuts repo rate today', 'feed', 'RBI cuts repo rate today'),
        ('/myfeed list', 'myfeed', 'list'),
        ('/myfeed today', 'myfeed', 'today'),
        ('/myfeed scan', 'myfeed', 'scan'),
    ):
        cmd, args = parse_command(raw)
        if cmd != expected_cmd or args != expected_args:
            return _fail(
                f'parse_command({raw!r}) => ({cmd!r}, {args!r}) '
                f'expected ({expected_cmd!r}, {expected_args!r})'
            )

    for alias in ('/feed news', '/feed news NIFTY rally', '/myfeed add', '/myfeed news'):
        cmd, args = parse_command(alias)
        if cmd == 'feed':
            return _fail(f'alias must not map to feed: {alias!r} => ({cmd!r}, {args!r})')
        if cmd != 'removed_feed_alias':
            return _fail(f'removed alias must be rejected: {alias!r} => ({cmd!r}, {args!r})')

    if not is_feed_caption('/feed'):
        return _fail('/feed caption must be accepted')
    if not is_feed_caption('/feed extra headline text'):
        return _fail('/feed <extra> caption must be accepted')
    for bad in ('/feed news', '/myfeed add', '/myfeed news', '/myfeed today'):
        if is_feed_caption(bad):
            return _fail(f'is_feed_caption must reject {bad!r}')

    if '/feed news' in HELP_TEXT or '/myfeed add' in HELP_TEXT or '/myfeed news' in HELP_TEXT:
        return _fail('HELP_TEXT must not list feed aliases')
    if '/feed — add market news text or screenshot' not in HELP_TEXT.replace('<', '').replace('>', ''):
        if '/feed — add market news text or screenshot' not in HELP_TEXT:
            return _fail('HELP_TEXT must document single /feed command')
    if FEED_PENDING_REPLY != 'Send market news text or screenshot now.':
        return _fail('FEED_PENDING_REPLY mismatch')

    print('TELEGRAM_FEED_SINGLE_COMMAND_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
