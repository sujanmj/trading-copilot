#!/usr/bin/env python3
"""Unit tests — outcome resolver status line rendering (Stage 49B)."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)


def _fail(msg: str) -> int:
    print(f'OUTCOME_RESOLVER_STATUS_RENDER_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.storage.outcome_resolver import format_outcome_resolver_status_lines, is_outcome_resolver_installed

    if not is_outcome_resolver_installed():
        return _fail('resolver must be installed in this repo')

    with patch('backend.storage.outcome_resolver._load_resolver_state', return_value={}):
        awaiting_lines = format_outcome_resolver_status_lines()
    joined = ' '.join(awaiting_lines)
    if 'not active yet' in joined.lower():
        return _fail('installed resolver must not say not active yet')
    if 'awaiting eligible close/reference price data' not in joined:
        return _fail(f'missing awaiting message got {awaiting_lines!r}')

    with patch(
        'backend.storage.outcome_resolver._load_resolver_state',
        return_value={
            'last_run_at': '2026-05-27T11:30:00+00:00',
            'last_summary': {
                'resolved_new': 5,
                'skipped_no_price': 12,
                'skipped_not_due': 3,
                'errors': 0,
            },
        },
    ):
        run_lines = format_outcome_resolver_status_lines()
    run_joined = '\n'.join(run_lines)
    if 'Outcome resolver active.' not in run_joined:
        return _fail('last run must show Outcome resolver active.')
    if 'Last resolver run:' not in run_joined:
        return _fail('last run must include timestamp')
    if 'resolved_new=5' not in run_joined or 'skipped_no_price=12' not in run_joined:
        return _fail(f'last run summary missing counts: {run_joined!r}')

    with patch('backend.storage.outcome_resolver.is_outcome_resolver_installed', return_value=False):
        inactive = format_outcome_resolver_status_lines()
    if inactive != ['Outcome resolver not active yet.']:
        return _fail(f'uninstalled resolver message wrong: {inactive!r}')

    print('OUTCOME_RESOLVER_STATUS_RENDER_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
