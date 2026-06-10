#!/usr/bin/env python3
"""Unit tests — final My Feed Telegram view commands (Stage 50B final)."""

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
    print(f'MYFEED_COMMANDS_FINAL_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    tmp = tempfile.mkdtemp()
    try:
        db_path = Path(tmp) / 'my_feed.db'
        with patch('backend.my_feed.my_feed_db.get_my_feed_db_path', return_value=db_path):
            from backend.telegram.lazy_command_runner import run_myfeed_only
            from backend.telegram.telegram_analysis_bot import HELP_TEXT, handle_analysis_command, parse_command

            for cmd_text, expected_args in (
                ('/myfeed list', 'list'),
                ('/myfeed today', 'today'),
                ('/myfeed scan', 'scan'),
            ):
                cmd, args = parse_command(cmd_text)
                if cmd != 'myfeed' or args != expected_args:
                    return _fail(f'parse_command({cmd_text!r}) => ({cmd!r}, {args!r})')

            for label in ('/myfeed list', '/myfeed today', '/myfeed scan'):
                if label not in HELP_TEXT:
                    return _fail(f'HELP_TEXT missing {label}')

            if '/feed news' in HELP_TEXT or '/myfeed add' in HELP_TEXT:
                return _fail('HELP_TEXT must not list removed feed aliases')

            from backend.my_feed.feed_processor import ingest_text

            ingest_text('NIFTY gains on banking sector rally today', source='telegram_text')

            for args in ('list', 'today', 'scan'):
                result = run_myfeed_only(args)
                text = str(result.get('text') or '')
                if not text:
                    return _fail(f'run_myfeed_only({args!r}) returned empty text')
                if args == 'list' and 'My Feed' not in text:
                    return _fail('/myfeed list formatter missing title')
                if args == 'today' and 'today' not in text.lower():
                    return _fail('/myfeed today formatter missing today label')
                if args == 'scan' and 'scan' not in text.lower():
                    return _fail('/myfeed scan formatter missing scan label')

                dry = handle_analysis_command(f'/myfeed {args}', dry_run=True)
                dry_text = str(dry[0].get('text') or '')
                if not dry_text:
                    return _fail(f'handle_analysis_command /myfeed {args} returned empty')
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print('MYFEED_COMMANDS_FINAL_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
