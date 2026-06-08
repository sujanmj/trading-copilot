#!/usr/bin/env python3
"""Unit tests for Telegram unknown command suggestions (Stage 48J)."""

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
    print(f'TELEGRAM_COMMAND_SUGGESTIONS_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.telegram.telegram_command_normalize import (
        format_unknown_command_response,
        suggest_command,
    )
    from backend.telegram.telegram_analysis_bot import handle_analysis_command
    from backend.telegram.response_format import strip_stage_markers

    cases = (
        ('aihun', '', '/aihub'),
        ('callib', '', '/aihub calib'),
        ('action', '', '/action plan'),
        ('theme', 'search', '/theme search'),
        ('theme', 'overview', '/theme'),
    )
    for cmd, args, expected in cases:
        suggestion = suggest_command(cmd, args)
        if expected not in (suggestion or ''):
            return _fail(f'suggest_command({cmd}, {args}) expected {expected}, got {suggestion}')

    text = format_unknown_command_response('aihun')
    if 'Unknown command' not in text or 'Did you mean /aihub?' not in text:
        return _fail(f'bad aihun response: {text!r}')

    results = handle_analysis_command('aihun', 'test', dry_run=True)
    routed = strip_stage_markers(str((results[0] or {}).get('text') or ''))
    if 'Did you mean /aihub?' not in routed:
        return _fail('handle_analysis_command aihun missing suggestion')

    print('TELEGRAM_COMMAND_SUGGESTIONS_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
