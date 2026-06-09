#!/usr/bin/env python3
"""Unit tests — /full must not run outcome resolver (Stage 49A)."""

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
    print(f'FULL_DOES_NOT_RUN_OUTCOME_RESOLVER_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.config.local_safe_mode import ASTRAEDGE_TELEGRAM_BUILD
    from backend.telegram import telegram_analysis_bot as tab
    from backend.telegram.lazy_command_runner import FULL_SNAPSHOT_SEQUENCE

    if ASTRAEDGE_TELEGRAM_BUILD != 'AstraEdge 49C':
        return _fail(f'expected AstraEdge 49C got {ASTRAEDGE_TELEGRAM_BUILD!r}')

    if len(FULL_SNAPSHOT_SEQUENCE) != 33:
        return _fail(f'/full must remain 33 steps got {len(FULL_SNAPSHOT_SEQUENCE)}')

    resolver_calls: list[int] = []

    def _track_resolver(**kwargs):
        resolver_calls.append(1)
        return {'resolved_new': 0}

    def _snapshot_stub(text: str, from_user: str = 'unknown', *, dry_run: bool = False, in_full_snapshot: bool = False):
        if not in_full_snapshot:
            return _fail('expected in_full_snapshot') or []
        return [{'ok': True, 'text': f'stub:{text}'}]

    with patch('backend.storage.outcome_resolver.run_outcome_resolver_once', side_effect=_track_resolver):
        with patch('backend.storage.outcome_resolver.run_after_close_outcome_resolver_if_due', side_effect=_track_resolver):
            with patch.object(tab, 'handle_analysis_command', side_effect=_snapshot_stub):
                tab._handle_full_snapshot(dry_run=True)

    if resolver_calls:
        return _fail('/full must not invoke outcome resolver')

    print('FULL_DOES_NOT_RUN_OUTCOME_RESOLVER_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
