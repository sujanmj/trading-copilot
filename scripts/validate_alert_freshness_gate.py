#!/usr/bin/env python3
"""Validate alert freshness gate pack (Stage 46H)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)


def _fail(msg: str) -> int:
    print(f'ALERT_FRESHNESS_GATE_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    path = PROJECT_ROOT / 'backend/orchestration/alert_freshness_gate.py'
    if not path.is_file():
        return _fail('missing alert_freshness_gate.py')
    src = path.read_text(encoding='utf-8')
    if 'Data refresh incomplete' not in src:
        return _fail('missing watch-only message')
    if os.system(f'{sys.executable} scripts/test_alert_freshness_gate.py') != 0:
        return _fail('test_alert_freshness_gate.py failed')
    print('ALERT_FRESHNESS_GATE_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
