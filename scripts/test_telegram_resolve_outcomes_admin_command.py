#!/usr/bin/env python3
"""Unit tests — /resolve outcomes admin command (Stage 49D)."""

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
    print(f'TELEGRAM_RESOLVE_OUTCOMES_ADMIN_COMMAND_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.telegram import telegram_analysis_bot as tab

    summary = {
        'pending_before': 63,
        'resolved_new': 4,
        'pending_after': 59,
        'skipped_missing_reference': 1,
        'skipped_missing_evaluation': 2,
        'errors': 0,
    }

    with patch.dict(os.environ, {'TELEGRAM_ADMIN_USER': 'adminuser'}, clear=False):
        with patch('backend.storage.outcome_resolver.run_outcome_resolver_once', return_value=summary):
            denied = tab.handle_analysis_command('/resolve outcomes', from_user='other', dry_run=True)
            allowed = tab.handle_analysis_command('/resolve outcomes', from_user='adminuser', dry_run=True)

    denied_text = denied[0].get('text', '') if denied else ''
    if 'Unauthorized' not in denied_text:
        return _fail(f'non-admin must be rejected got {denied_text!r}')

    allowed_text = allowed[0].get('text', '') if allowed else ''
    for needle in (
        'OUTCOME_RESOLVER_RUN_OK',
        'pending_before=63',
        'resolved_new=4',
        'pending_after=59',
        'skipped_missing_reference=1',
        'skipped_missing_evaluation=2',
        'errors=0',
    ):
        if needle not in allowed_text:
            return _fail(f'admin /resolve outcomes missing {needle!r} in {allowed_text!r}')

    cmd, args = tab.parse_command('/resolve outcomes')
    if cmd != 'resolve' or args != 'outcomes':
        return _fail(f'parse_command /resolve outcomes unexpected: {cmd!r} {args!r}')

    help_text = tab.HELP_TEXT.lower()
    if 'resolve outcomes' in help_text or '/outcomes' in help_text:
        return _fail('admin commands must not appear in /help')

    print('TELEGRAM_RESOLVE_OUTCOMES_ADMIN_COMMAND_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
