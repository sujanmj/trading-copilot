#!/usr/bin/env python3
"""Validate Stage 50L watch/avoid contradiction guard."""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)


def _fail(msg: str) -> int:
    print(f'OBSERVATION_NO_WATCH_AVOID_CONTRADICTION_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    src = (PROJECT_ROOT / 'backend/analytics/unified_decision_engine.py').read_text(encoding='utf-8')
    for needle in ('filter_rows_exclude_avoid', 'filter_ticker_list_exclude_avoid', 'is_avoid_or_rejected'):
        if needle not in src:
            return _fail(f'unified_decision_engine missing {needle}')
    proc = os.system(f'{sys.executable} scripts/test_observation_no_watch_avoid_contradiction.py')
    if proc != 0:
        return _fail('test_observation_no_watch_avoid_contradiction.py failed')
    print('OBSERVATION_NO_WATCH_AVOID_CONTRADICTION_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
