#!/usr/bin/env python3
"""Unit tests — after-close scheduler outcome resolver hook (Stage 49A)."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)


def _fail(msg: str) -> int:
    print(f'OUTCOME_RESOLVER_AFTER_CLOSE_SCHEDULER_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.storage import outcome_resolver
    from backend.telegram import telegram_brief_scheduler as sched

    calls: list[dict] = []

    def _fake_run(*, now=None):
        calls.append({'now': now})
        return {'resolved_new': 2, 'pending_after': 188, 'errors': 0}

    with tempfile.TemporaryDirectory() as tmp:
        state_file = Path(tmp) / 'outcome_resolver_last_run.json'
        with patch.object(outcome_resolver, 'OUTCOME_RESOLVER_STATE_FILE', state_file):
            with patch(
                'backend.storage.outcome_resolver.run_outcome_resolver_once',
                return_value={'resolved_new': 2, 'pending_after': 188, 'errors': 0},
            ):
                ist = ZoneInfo('Asia/Kolkata')
                after_close = datetime(2026, 5, 27, 16, 45, tzinfo=ist)
                first = outcome_resolver.run_after_close_outcome_resolver_if_due(now=after_close)
                second = outcome_resolver.run_after_close_outcome_resolver_if_due(now=after_close)
                if int(first.get('resolved_new') or 0) != 2:
                    return _fail(f'first after-close run should resolve got {first!r}')
                if second.get('skipped') != 'already_ran_today':
                    return _fail(f'second run same day must skip got {second!r}')

                before_close = datetime(2026, 5, 27, 14, 0, tzinfo=ist)
                early = outcome_resolver.run_after_close_outcome_resolver_if_due(now=before_close)
                if early.get('skipped') != 'before_india_close':
                    return _fail(f'before close must skip got {early!r}')

        hook_calls: list[int] = []

        def _hook(**kwargs):
            hook_calls.append(1)
            return {'resolved_new': 1, 'pending_after': 1, 'errors': 0}

        with patch('backend.storage.outcome_resolver.run_after_close_outcome_resolver_if_due', side_effect=_hook):
            sched._maybe_run_after_close_outcome_resolver(datetime(2026, 5, 27, 16, 45, tzinfo=ZoneInfo('Asia/Kolkata')))

        if not hook_calls:
            return _fail('scheduler hook must call after-close resolver safely')

    print('OUTCOME_RESOLVER_AFTER_CLOSE_SCHEDULER_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
