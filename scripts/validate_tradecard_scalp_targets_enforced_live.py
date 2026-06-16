#!/usr/bin/env python3
"""Validate Stage 50S scalp target enforcement test."""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)


def _fail(msg: str) -> int:
    print(f'TRADECARD_SCALP_TARGETS_ENFORCED_LIVE_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    proc = os.system(f'{sys.executable} scripts/test_tradecard_scalp_targets_enforced_live.py')
    if proc != 0:
        return _fail('test_tradecard_scalp_targets_enforced_live.py failed')
    print('TRADECARD_SCALP_TARGETS_ENFORCED_LIVE_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
