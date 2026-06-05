#!/usr/bin/env python3
"""Validate emergency macro severity pack (Stage 46I)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)


def _fail(msg: str) -> int:
    print(f'EMERGENCY_MACRO_SEVERITY_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    src = (PROJECT_ROOT / 'backend/orchestration/alert_quality_filters.py').read_text(encoding='utf-8')
    for needle in (
        'classify_macro_severity',
        'is_stock_specific_risk',
        'is_broad_macro_emergency',
        'stock_specific',
    ):
        if needle not in src:
            return _fail(f'alert_quality_filters missing {needle}')

    proc = os.system(f'{sys.executable} scripts/test_emergency_macro_severity.py')
    if proc != 0:
        return _fail('test_emergency_macro_severity.py failed')

    print('EMERGENCY_MACRO_SEVERITY_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
