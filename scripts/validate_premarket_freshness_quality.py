#!/usr/bin/env python3
"""Validate premarket freshness quality pack (Stage 46I)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)


def _fail(msg: str) -> int:
    print(f'PREMARKET_FRESHNESS_QUALITY_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    for rel in (
        'backend/analytics/premarket_conviction.py',
        'backend/orchestration/alert_freshness_gate.py',
    ):
        if not (PROJECT_ROOT / rel).is_file():
            return _fail(f'missing {rel}')

    gate_src = (PROJECT_ROOT / 'backend/orchestration/alert_freshness_gate.py').read_text(encoding='utf-8')
    for needle in ('PREMARKET_INCOMPLETE_HEADER', 'premarket_freshness_state', 'cap_premarket_scores'):
        if needle not in gate_src:
            return _fail(f'alert_freshness_gate missing {needle}')

    proc = os.system(f'{sys.executable} scripts/test_premarket_freshness_quality.py')
    if proc != 0:
        return _fail('test_premarket_freshness_quality.py failed')

    print('PREMARKET_FRESHNESS_QUALITY_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
