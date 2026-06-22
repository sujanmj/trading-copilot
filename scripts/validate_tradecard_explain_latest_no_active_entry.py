#!/usr/bin/env python3
"""Validate Stage 50Z latest no-active tradecard explain hotfix."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

TEST_MARKER = 'TRADECARD_EXPLAIN_LATEST_NO_ACTIVE_ENTRY_TEST_OK'
MARKER = 'TRADECARD_EXPLAIN_LATEST_NO_ACTIVE_ENTRY_OK'


def _fail(msg: str) -> int:
    print(f'TRADECARD_EXPLAIN_LATEST_NO_ACTIVE_ENTRY_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    latest_src = (PROJECT_ROOT / 'backend/trading/tradecard_latest.py').read_text(encoding='utf-8')
    fmt_src = (PROJECT_ROOT / 'backend/telegram/response_format.py').read_text(encoding='utf-8')
    for token in ('latest_tradecard_audit', 'audit_only', 'AUDIT_ONLY_STATUSES'):
        if token not in latest_src:
            return _fail(f'tradecard_latest.py missing {token}')
    for token in ('Entry logic: no active entry generated', 'save_latest_tradecard', 'audit_only=True'):
        if token not in fmt_src:
            return _fail(f'response_format.py missing {token}')

    proc = subprocess.run(
        [sys.executable, 'scripts/test_tradecard_explain_latest_no_active_entry.py'],
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
