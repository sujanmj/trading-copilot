#!/usr/bin/env python3
"""Validate scanner session-date guard (Stage 47D)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)


def _fail(msg: str) -> int:
    print(f'SCANNER_SESSION_DATE_GUARD_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    conv_src = (PROJECT_ROOT / 'backend/analytics/premarket_conviction.py').read_text(encoding='utf-8')
    gate_src = (PROJECT_ROOT / 'backend/orchestration/alert_freshness_gate.py').read_text(encoding='utf-8')
    for needle in ('_annotate_setup_row', 'previous_session_research', 'previous_session_movers'):
        if needle not in conv_src:
            return _fail(f'premarket_conviction missing {needle}')
    for needle in ('session_date', 'annotate_candidate_session', 'is_current_trading_session'):
        if needle not in gate_src:
            return _fail(f'alert_freshness_gate missing {needle}')

    if os.system(f'{sys.executable} scripts/test_scanner_session_date_guard.py') != 0:
        return _fail('test_scanner_session_date_guard.py failed')

    print('SCANNER_SESSION_DATE_GUARD_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
