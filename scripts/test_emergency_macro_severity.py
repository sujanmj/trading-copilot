#!/usr/bin/env python3
"""Unit tests for emergency macro severity classification (Stage 46I)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)


def _fail(msg: str) -> int:
    print(f'EMERGENCY_MACRO_SEVERITY_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.orchestration.alert_quality_filters import (
        classify_macro_severity,
        evaluate_emergency_macro,
        is_broad_macro_emergency,
        is_stock_specific_risk,
    )

    icici = 'SEBI issues warning to ICICI Bank over compliance lapses'
    if not is_stock_specific_risk(icici):
        return _fail('ICICI SEBI warning should be stock-specific')
    if is_broad_macro_emergency(icici):
        return _fail('ICICI single-stock warning should not be broad macro')
    if classify_macro_severity(icici) != 'stock_specific':
        return _fail('ICICI severity should be stock_specific')

    ok, reason, _theme = evaluate_emergency_macro(icici, 0.9)
    if ok:
        return _fail('ICICI warning should not send as emergency macro')
    if reason != 'stock_specific':
        return _fail(f'expected stock_specific skip, got {reason}')

    banking = 'Banking sector under pressure as Nifty Bank slides 3% on FII outflows'
    if not is_broad_macro_emergency(banking):
        return _fail('sector-wide banking headline should be broad macro')
    ok2, reason2, _ = evaluate_emergency_macro(banking, 0.85)
    if not ok2:
        return _fail(f'broad banking macro should send, got reason={reason2}')

    rbi = 'RBI surprises with emergency repo rate hike'
    if classify_macro_severity(rbi) != 'emergency_macro':
        return _fail('RBI policy should remain emergency_macro')

    generic = 'Wall Street closes mixed ahead of jobs data'
    ok3, reason3, _ = evaluate_emergency_macro(generic, 0.8)
    if ok3:
        return _fail('generic global headline should be downgraded')

    print('EMERGENCY_MACRO_SEVERITY_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
