#!/usr/bin/env python3
"""Validate Budget frontend tab pack (Stage 48A)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _fail(msg: str) -> int:
    print(f'BUDGET_FRONTEND_TAB_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    proc = subprocess.run([sys.executable, 'scripts/test_budget_frontend_tab.py'], cwd=PROJECT_ROOT)
    if proc.returncode != 0:
        return _fail('test_budget_frontend_tab.py failed')
    print('BUDGET_FRONTEND_TAB_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
