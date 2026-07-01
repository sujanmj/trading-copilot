#!/usr/bin/env python3
"""Phase 4B.4 — /full aligns with opening rally workflow."""

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

OPENING_FULL_SEQUENCE = (
    '/status',
    '/health',
    '/schedule',
    '/memory',
    '/broker',
    '/qa',
    '/news',
    '/catalysts today',
    '/radar',
    '/tradecards',
    '/tradecard',
    '/close',
)

REMOVED_FROM_FULL = (
    '/premarket',
    '/premarket full',
    '/action plan',
    '/today',
    '/tomorrow',
    '/morning',
)

MANUAL_COMMANDS = (
    '/premarket',
    '/premarket full',
    '/action plan',
    '/today',
    '/tomorrow',
    '/morning',
)


def _fail(msg: str) -> int:
    print(f'FULL_OPENING_WORKFLOW_4B4_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.telegram import telegram_analysis_bot as tab
    from backend.telegram.lazy_command_runner import FULL_SNAPSHOT_SEQUENCE

    if tuple(FULL_SNAPSHOT_SEQUENCE) != OPENING_FULL_SEQUENCE:
        return _fail(f'FULL_SNAPSHOT_SEQUENCE mismatch: {FULL_SNAPSHOT_SEQUENCE!r}')

    for cmd in ('/radar', '/tradecards', '/tradecard', '/schedule'):
        if cmd not in FULL_SNAPSHOT_SEQUENCE:
            return _fail(f'/full must include {cmd}')

    for cmd in REMOVED_FROM_FULL:
        if cmd in FULL_SNAPSHOT_SEQUENCE:
            return _fail(f'/full must not include {cmd}')

    calls: list[str] = []

    def _step_handle(
        text: str,
        from_user: str = 'unknown',
        *,
        dry_run: bool = False,
        in_full_snapshot: bool = False,
        chat_id: str | None = None,
    ):
        if not in_full_snapshot:
            return _fail('inner snapshot steps must set in_full_snapshot=True') or []
        calls.append(text)
        return [{'ok': True, 'dry_run': dry_run, 'text': f'body:{text}'}]

    with patch.object(tab, 'handle_analysis_command', side_effect=_step_handle):
        results = tab._handle_full_snapshot(dry_run=True)

    if calls != list(OPENING_FULL_SEQUENCE):
        return _fail(f'/full invoked {calls!r}')

    texts = [str(r.get('text') or '') for r in results]
    if not any('AstraEdge Full — opening workflow view' in t for t in texts):
        return _fail('/full title must say opening workflow view')
    if not any('Step 01/12 — /status' in t for t in texts):
        return _fail('missing Step 01/12 prefix')
    if not any('Step 12/12 — /close' in t for t in texts):
        return _fail('missing Step 12/12 prefix')

    for cmd in MANUAL_COMMANDS:
        with patch('backend.telegram.lazy_command_runner.run_radar_only', return_value={'text': 'x'}):
            results = tab.handle_analysis_command(cmd, 'manual_test', dry_run=True)
        if not results:
            return _fail(f'manual {cmd} must still work')

    print('FULL_OPENING_WORKFLOW_4B4_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
