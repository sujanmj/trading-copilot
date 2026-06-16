#!/usr/bin/env python3
"""Stage 50P — /full includes /catalysts today and /tradecard (34 steps)."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _fail(msg: str) -> int:
    print(f'FULL_INCLUDES_CATALYSTS_TRADECARD_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.telegram.lazy_command_runner import FULL_SNAPSHOT_SEQUENCE

    if len(FULL_SNAPSHOT_SEQUENCE) != 34:
        return _fail(f'expected 34 /full steps got {len(FULL_SNAPSHOT_SEQUENCE)}')
    if '/catalysts today' not in FULL_SNAPSHOT_SEQUENCE:
        return _fail('/full must include /catalysts today')
    if '/tradecard' not in FULL_SNAPSHOT_SEQUENCE:
        return _fail('/full must include /tradecard')
    if FULL_SNAPSHOT_SEQUENCE.index('/catalysts today') >= FULL_SNAPSHOT_SEQUENCE.index('/tradecard'):
        return _fail('/catalysts today should appear before /tradecard in /full sequence')

    print('FULL_INCLUDES_CATALYSTS_TRADECARD_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
