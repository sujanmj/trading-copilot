#!/usr/bin/env python3
"""Unit tests — outcome_resolver_status.py script (Stage 49B)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)


def _fail(msg: str) -> int:
    print(f'OUTCOME_RESOLVER_STATUS_SCRIPT_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    proc = subprocess.run(
        [sys.executable, 'scripts/outcome_resolver_status.py'],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return _fail(f'script exit {proc.returncode}: {proc.stderr[:300]}')
    out = proc.stdout
    if 'OUTCOME_RESOLVER_STATUS_OK' not in out:
        return _fail('missing OUTCOME_RESOLVER_STATUS_OK')
    for key in (
        'resolver_active=',
        'last_run=',
        'resolved_total=',
        'pending_total=',
        'skipped_no_price=',
        'skipped_not_due=',
        'errors=',
        'data_root=',
    ):
        if key not in out:
            return _fail(f'missing {key!r} in output')

    from backend.storage.outcome_resolver import get_outcome_resolver_status, is_outcome_resolver_installed

    if not is_outcome_resolver_installed():
        return _fail('resolver should be installed')
    status = get_outcome_resolver_status()
    if status.get('resolver_active') is not True:
        return _fail('status snapshot must report resolver_active=True')

    print('OUTCOME_RESOLVER_STATUS_SCRIPT_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
