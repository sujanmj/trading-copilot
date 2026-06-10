#!/usr/bin/env python3
"""Stage 50G — /myfeed shortcut removed."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _fail(msg: str) -> int:
    print(f'MYFEED_REMOVE_DUPLICATE_SHORTCUT_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.telegram.telegram_analysis_bot import HELP_TEXT, handle_analysis_command, parse_command

    cmd, args = parse_command('/myfeed')
    if cmd != 'myfeed' or args != '':
        return _fail('/myfeed alone must not alias to list')

    if '/myfeed — latest saved feed (same as /myfeed list)' in HELP_TEXT:
        return _fail('help must not advertise /myfeed shortcut')

    for sub in ('list', 'today', 'scan'):
        c, a = parse_command(f'/myfeed {sub}')
        if c != 'myfeed' or a != sub:
            return _fail(f'/myfeed {sub} must parse correctly')

    usage = handle_analysis_command('/myfeed', dry_run=True)
    usage_text = str((usage[0] or {}).get('text') or '')
    if 'list' not in usage_text or 'today' not in usage_text or 'scan' not in usage_text:
        return _fail('/myfeed alone must show subcommand usage')

    listed = handle_analysis_command('/myfeed list', dry_run=True)
    if not listed:
        return _fail('/myfeed list must produce a response')

    print('MYFEED_REMOVE_DUPLICATE_SHORTCUT_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
