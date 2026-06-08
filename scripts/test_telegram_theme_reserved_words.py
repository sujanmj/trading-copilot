#!/usr/bin/env python3
"""Unit tests for Telegram theme reserved words (Stage 48J)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)


def _fail(msg: str) -> int:
    print(f'TELEGRAM_THEME_RESERVED_WORDS_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.analytics.theme_baskets import handle_theme_command

    cases = (
        ('', 'Commands:'),
        ('overview', 'Commands:'),
        ('search', '/theme search bank'),
        ('category', 'Available:'),
        ('list', 'Wishlist'),
    )
    for args, needle in cases:
        text = handle_theme_command(args)
        if 'Unknown theme' in text:
            return _fail(f'theme {args!r} returned Unknown theme')
        if needle not in text:
            return _fail(f'theme {args!r} missing {needle!r}')

    from backend.telegram.telegram_analysis_bot import handle_analysis_command
    from backend.telegram.response_format import strip_stage_markers

    for cmd in ('theme overview', '/theme overview'):
        results = handle_analysis_command(cmd, 'test', dry_run=True)
        text = strip_stage_markers(str((results[0] or {}).get('text') or ''))
        if 'Unknown theme' in text or 'Unknown command' in text:
            return _fail(f'{cmd} failed')

    print('TELEGRAM_THEME_RESERVED_WORDS_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
