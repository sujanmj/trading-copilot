#!/usr/bin/env python3
"""Validate live watch / premarket consistency (Stage 47F)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)


def _fail(msg: str) -> int:
    print(f'LIVE_WATCH_CONSISTENCY_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    pre_src = (PROJECT_ROOT / 'backend/analytics/premarket_conviction.py').read_text(encoding='utf-8')
    gate_src = (PROJECT_ROOT / 'backend/orchestration/alert_freshness_gate.py').read_text(encoding='utf-8')
    for needle in (
        "'stage': '48A'",
        'Previous-session / stale research only',
        'Context partially stale',
        'CRITICAL_MARKET_HOURS_KEYS',
        'PREMARKET_INCOMPLETE_SCORE_CAP',
    ):
        if needle not in pre_src and needle not in gate_src:
            return _fail(f'missing {needle!r} in premarket/freshness modules')

    if os.system(f'{sys.executable} scripts/test_live_watch_consistency.py') != 0:
        return _fail('test_live_watch_consistency.py failed')
    print('LIVE_WATCH_CONSISTENCY_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
