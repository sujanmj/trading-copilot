#!/usr/bin/env python3
"""Stage 50L — emergency macro severity filter for local bank news."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _fail(msg: str) -> int:
    print(f'EMERGENCY_MACRO_SEVERITY_FILTER_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.orchestration.alert_quality_filters import (
        classify_macro_severity,
        evaluate_emergency_macro,
        is_local_bank_low_impact,
        macro_display_class,
    )

    mogaveera = 'RBI imposes restrictions on Mogaveera Co-operative Bank'
    if not is_local_bank_low_impact(mogaveera):
        return _fail('Mogaveera cooperative bank should be low impact')
    if classify_macro_severity(mogaveera) != 'info_macro_low_impact':
        return _fail('Mogaveera should classify as info_macro_low_impact')
    ok, reason, _ = evaluate_emergency_macro(mogaveera, 0.9)
    if ok:
        return _fail('local cooperative bank must not send as emergency macro')
    if macro_display_class(mogaveera) != 'INFO MACRO / LOW MARKET IMPACT':
        return _fail('display class should be INFO MACRO / LOW MARKET IMPACT')

    rbi = 'RBI surprises markets with emergency repo rate hike'
    if classify_macro_severity(rbi) != 'emergency_macro':
        return _fail('RBI policy rate shock should remain emergency_macro')

    print('EMERGENCY_MACRO_SEVERITY_FILTER_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
