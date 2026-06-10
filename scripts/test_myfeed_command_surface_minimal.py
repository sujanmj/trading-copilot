#!/usr/bin/env python3
"""Unit tests — minimal My Feed command surface in help (Stage 50C)."""

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
    print(f'MYFEED_COMMAND_SURFACE_MINIMAL_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.config.local_safe_mode import ASTRAEDGE_TELEGRAM_BUILD
    from backend.telegram.telegram_analysis_bot import HELP_TEXT, handle_analysis_command, parse_command

    if ASTRAEDGE_TELEGRAM_BUILD != 'AstraEdge 50C':
        return _fail(f'expected AstraEdge 50C got {ASTRAEDGE_TELEGRAM_BUILD!r}')

    for forbidden in ('/feed news', '/myfeed add', '/myfeed news', '/ feed'):
        if forbidden in HELP_TEXT:
            return _fail(f'HELP_TEXT must not list {forbidden!r}')

    for required in (
        '/feed — add market news text or screenshot',
        '/myfeed list — latest saved feed',
        '/myfeed today — today\'s feed',
        '/myfeed scan — tickers/themes impact',
    ):
        if required not in HELP_TEXT:
            return _fail(f'HELP_TEXT missing {required!r}')

    cmd, args = parse_command('/myfeed')
    if cmd != 'myfeed' or args != 'list':
        return _fail(f'/myfeed must shortcut to list, got ({cmd!r}, {args!r})')

    tmp = tempfile.mkdtemp()
    try:
        db_path = Path(tmp) / 'my_feed.db'
        with patch('backend.my_feed.my_feed_db.get_my_feed_db_path', return_value=db_path):
            from backend.my_feed.feed_processor import ingest_text

            ingest_text('NIFTY gains on banking sector rally today', source='telegram_text')

            for args in ('list', 'today', 'scan'):
                dry = handle_analysis_command(f'/myfeed {args}', dry_run=True)
                dry_text = str(dry[0].get('text') or '')
                if not dry_text:
                    return _fail(f'/myfeed {args} returned empty response')

            shortcut = handle_analysis_command('/myfeed', dry_run=True)
            shortcut_text = str(shortcut[0].get('text') or '')
            list_cmd = handle_analysis_command('/myfeed list', dry_run=True)
            list_text = str(list_cmd[0].get('text') or '')
            if not shortcut_text or not list_text:
                return _fail('/myfeed shortcut must return list output')
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print('MYFEED_COMMAND_SURFACE_MINIMAL_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
