#!/usr/bin/env python3
"""Unit tests for /full snapshot sequence (Stage 48P)."""

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
    print(f'TELEGRAM_FULL_SEQUENCE_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.telegram import telegram_analysis_bot as tab
    from backend.telegram.lazy_command_runner import FULL_SNAPSHOT_SEQUENCE

    expected = [
        '/status', '/health', '/schedule', '/memory', '/broker', '/broker evidence',
        '/qa', '/action plan', '/today', '/tomorrow', '/premarket', '/premarket full',
        '/aihub full', '/aihub brain', '/aihub govt', '/aihub scan', '/aihub market',
        '/aihub global', '/aihub news', '/aihub tv', '/aihub calib',
        '/aihub journal', '/news', '/morning', '/close', '/theme', '/theme list',
        '/theme budget', '/theme news infra', '/theme scan infra', '/budget',
        '/budget theme infra',
    ]
    if list(FULL_SNAPSHOT_SEQUENCE) != expected:
        return _fail('FULL_SNAPSHOT_SEQUENCE mismatch')
    if len(FULL_SNAPSHOT_SEQUENCE) != 32:
        return _fail(f'expected 32 steps, got {len(FULL_SNAPSHOT_SEQUENCE)}')

    calls: list[str] = []

    def _step_handle(text: str, from_user: str = 'unknown', *, dry_run: bool = False, in_full_snapshot: bool = False):
        if not in_full_snapshot:
            return _fail('inner snapshot steps must set in_full_snapshot=True') or []
        calls.append(text)
        if text == '/schedule':
            raise RuntimeError('schedule unavailable')
        return [{'ok': True, 'dry_run': dry_run, 'text': f'body:{text}'}]

    with patch.object(tab, 'handle_analysis_command', side_effect=_step_handle):
        results = tab._handle_full_snapshot(dry_run=True)

    if calls != expected:
        return _fail(f'sequence calls mismatch at index {len(calls)}')

    texts = [str(r.get('text') or '') for r in results]
    if not any('Step 01/32 — /status' in t for t in texts):
        return _fail('missing Step 01/32 prefix')
    if not any('Step 32/32 — /budget theme infra' in t for t in texts):
        return _fail('missing Step 32/32 prefix')
    if not any('Section unavailable:' in t and '/schedule' in t for t in texts):
        return _fail('schedule failure must continue with Section unavailable')
    if len(calls) != 32:
        return _fail('must invoke all 32 commands even after one failure')

    print('TELEGRAM_FULL_SEQUENCE_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
