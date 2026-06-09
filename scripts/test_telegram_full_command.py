#!/usr/bin/env python3
"""Unit tests for /full Telegram command (Stage 48P)."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

os.environ.setdefault('DISABLE_TELEGRAM', '1')
os.environ.setdefault('DISABLE_TELEGRAM_SENDS', '1')


def _fail(msg: str) -> int:
    print(f'TELEGRAM_FULL_COMMAND_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.telegram.telegram_analysis_bot import HELP_TEXT, handle_analysis_command

    if '/full — run all read-only AstraEdge commands one by one' not in HELP_TEXT:
        return _fail('/help missing Snapshot /full entry')
    if HELP_TEXT.count('/full') != 1:
        return _fail('/help must list only one /full entry')

    forbidden_help = (
        '/snapshot full',
        '/full compact',
        '/full refresh',
        'snapshot full',
        'full compact',
    )
    for needle in forbidden_help:
        if needle in HELP_TEXT:
            return _fail(f'/help must not include alias {needle!r}')

    with patch('backend.telegram.telegram_analysis_bot._handle_full_snapshot') as mock_full:
        mock_full.return_value = [{'ok': True, 'dry_run': True, 'text': 'mock'}]
        results = handle_analysis_command('/full', 'test_user', dry_run=True)
    if not mock_full.called:
        return _fail('/full must invoke full snapshot handler')
    if not results:
        return _fail('/full must return send results')

    print('TELEGRAM_FULL_COMMAND_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
