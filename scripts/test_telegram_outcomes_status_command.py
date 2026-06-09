#!/usr/bin/env python3
"""Unit tests — /outcomes Telegram command (Stage 49D)."""

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
    print(f'TELEGRAM_OUTCOMES_STATUS_COMMAND_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.telegram import telegram_analysis_bot as tab

    canonical = {
        'data_root': '/app/data',
        'resolved_total': 114,
        'pending_total': 63,
        'skipped_missing_reference': 2,
        'skipped_missing_evaluation': 1,
        'last_run': '2026-06-09T15:30:00+00:00',
        'errors': 0,
    }

    with patch('backend.storage.outcome_resolver.get_canonical_outcome_stats', return_value=canonical):
        results = tab.handle_analysis_command('/outcomes', from_user='tester', dry_run=True)
    text = results[0].get('text', '') if results else ''
    if not text:
        return _fail('empty /outcomes response')

    for needle in (
        'resolved_total=114',
        'pending_total=63',
        'skipped_missing_reference=2',
        'skipped_missing_evaluation=1',
        'last_run=2026-06-09T15:30:00+00:00',
        'errors=0',
        'data_root=/app/data',
    ):
        if needle not in text:
            return _fail(f'/outcomes missing {needle!r} in {text!r}')

    cmd, args = tab.parse_command('/outcomes')
    if cmd != 'outcomes' or args:
        return _fail(f'parse_command /outcomes unexpected: {cmd!r} {args!r}')

    print('TELEGRAM_OUTCOMES_STATUS_COMMAND_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
