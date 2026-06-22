#!/usr/bin/env python3
"""Validate Stage 50Z no-active audit watch-only rendering."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

TEST_MARKER = 'NO_ACTIVE_ENTRY_NOT_WATCH_FOR_ENTRY_TEST_OK'
MARKER = 'NO_ACTIVE_ENTRY_NOT_WATCH_FOR_ENTRY_OK'


def _fail(msg: str) -> int:
    print(f'NO_ACTIVE_ENTRY_NOT_WATCH_FOR_ENTRY_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    for path in (
        'backend/trading/unified_live_priority_engine.py',
        'backend/telegram/response_format.py',
        'backend/analytics/railway_decision_bootstrap.py',
    ):
        src = (PROJECT_ROOT / path).read_text(encoding='utf-8')
        if 'NEXT-SESSION WATCH ONLY' not in src:
            return _fail(f'{path} missing next-session watch-only downgrade')
    proc = subprocess.run(
        [sys.executable, 'scripts/test_no_active_entry_not_watch_for_entry.py'],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    output = (proc.stdout or '') + (proc.stderr or '')
    if proc.returncode != 0:
        return _fail(f'test failed rc={proc.returncode}: {output[-800:]}')
    if TEST_MARKER not in output:
        return _fail('test marker missing')

    print(MARKER)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
