#!/usr/bin/env python3
"""Unit tests for Telegram /action slashless aliases (Stage 48J)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

os.environ.setdefault('DISABLE_TELEGRAM', '1')
os.environ.setdefault('DISABLE_TELEGRAM_SENDS', '1')


def _fail(msg: str) -> int:
    print(f'TELEGRAM_COMMAND_ALIASES_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def _text(cmd: str) -> str:
    from backend.telegram.response_format import strip_stage_markers
    from backend.telegram.telegram_analysis_bot import handle_analysis_command

    results = handle_analysis_command(cmd, 'test_user', dry_run=True)
    if not results:
        return ''
    return strip_stage_markers(str(results[0].get('text') or ''))


def main() -> int:
    from backend.telegram.telegram_command_normalize import normalize_parsed_command

    for raw, expected_args in (
        ('action', 'plan'),
        ('/action', 'plan'),
        ('action plan', 'plan'),
        ('/action plan', 'plan'),
    ):
        cmd, args = normalize_parsed_command(*__import__('backend.telegram.telegram_analysis_bot', fromlist=['parse_command']).parse_command(raw))
        if cmd != 'action' or args != expected_args:
            return _fail(f'normalize failed for {raw!r}: {cmd=} {args=}')

    for cmd in ('/action', 'action', '/action plan', 'action plan'):
        text = _text(cmd)
        if 'Unknown command' in text:
            return _fail(f'{cmd} returned unknown command')
        if 'AstraEdge Action Plan' not in text and 'Action Plan' not in text:
            return _fail(f'{cmd} missing action plan title')

    print('TELEGRAM_COMMAND_ALIASES_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
