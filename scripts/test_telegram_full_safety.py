#!/usr/bin/env python3
"""Unit tests — /full safety (Stage 48P)."""

from __future__ import annotations

import os
import re
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
    print(f'TELEGRAM_FULL_SAFETY_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.telegram import telegram_analysis_bot as tab
    from backend.telegram.lazy_command_runner import FULL_SNAPSHOT_FORBIDDEN_ALIASES
    from backend.telegram.telegram_command_normalize import (
        _COMMAND_SUGGESTIONS,
        resolve_natural_command,
    )

    for alias in FULL_SNAPSHOT_FORBIDDEN_ALIASES:
        if alias in tab.HELP_TEXT:
            return _fail(f'help must not advertise alias {alias!r}')
        if alias.lstrip('/') in _COMMAND_SUGGESTIONS:
            return _fail(f'command suggestions must not include alias {alias!r}')

    if resolve_natural_command('snapshot full'):
        return _fail('natural routing must not map snapshot full')
    if resolve_natural_command('full compact'):
        return _fail('natural routing must not map full compact')

    sanitized = tab._sanitize_full_snapshot_error('anthropic timeout TELEGRAM_BOT_TOKEN leak')
    if 'anthropic' in sanitized.lower() or 'TELEGRAM_BOT_TOKEN' in sanitized:
        return _fail('error sanitizer must redact secrets and provider names')

    forbidden_output = ('buy now', 'guaranteed', 'sure shot')
    provider_patterns = (r'\bgroq\b', r'\banthropic\b', r'\bopenai\b', r'\bclaude\b', r'\bsonnet\b')

    def _snapshot_stub(text: str, from_user: str = 'unknown', *, dry_run: bool = False, in_full_snapshot: bool = False):
        if not in_full_snapshot:
            return []
        return [{'ok': True, 'text': '<b>Research only</b> — Watch for Entry'}]

    with patch.object(tab, 'handle_analysis_command', side_effect=_snapshot_stub):
        results = tab._handle_full_snapshot(dry_run=True)

    combined = '\n'.join(str(r.get('text') or '') for r in results).lower()
    for phrase in forbidden_output:
        if phrase in combined:
            return _fail(f'/full output must not contain forbidden phrase {phrase!r}')
    for pattern in provider_patterns:
        if re.search(pattern, combined, re.I):
            return _fail(f'/full output must not expose provider name matching {pattern}')

    print('TELEGRAM_FULL_SAFETY_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
