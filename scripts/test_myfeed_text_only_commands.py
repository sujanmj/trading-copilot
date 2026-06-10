#!/usr/bin/env python3
"""Stage 50G — My Feed Telegram text-only commands."""

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
    print(f'MYFEED_TEXT_ONLY_COMMANDS_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.telegram.my_feed_intake import FEED_TEXT_ONLY_USAGE
    from backend.telegram.telegram_analysis_bot import handle_analysis_command, parse_command

    cmd, args = parse_command('/feed')
    if cmd != 'feed' or args:
        return _fail('/feed alone must parse as feed with empty args')

    cmd2, args2 = parse_command('/feed TCS wins large AI cloud contract')
    if cmd2 != 'feed' or 'TCS' not in args2:
        return _fail('/feed <text> must capture market text')

    empty = handle_analysis_command('/feed', dry_run=True)
    text = str((empty[0] or {}).get('text') or '')
    if FEED_TEXT_ONLY_USAGE not in text and 'Send market news as text' not in text:
        return _fail(f'/feed without text must show usage, got {text!r}')

    tmp = tempfile.mkdtemp()
    try:
        db_path = Path(tmp) / 'my_feed.db'
        with patch('backend.my_feed.my_feed_db.get_my_feed_db_path', return_value=db_path):
            saved = handle_analysis_command('/feed TCS wins large AI cloud contract', dry_run=True)
        saved_text = str((saved[0] or {}).get('text') or '')
        if 'MY_FEED_SAVED' not in saved_text:
            return _fail(f'/feed with text must save, got {saved_text!r}')
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print('MYFEED_TEXT_ONLY_COMMANDS_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
