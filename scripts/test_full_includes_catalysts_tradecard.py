#!/usr/bin/env python3
"""Stage 4B.4 — /full includes opening workflow catalysts + tradecard steps."""

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

    if len(FULL_SNAPSHOT_SEQUENCE) != 12:
        return _fail(f'expected 12 /full steps got {len(FULL_SNAPSHOT_SEQUENCE)}')
    for cmd in ('/schedule', '/catalysts today', '/radar', '/tradecards', '/tradecard'):
        if cmd not in FULL_SNAPSHOT_SEQUENCE:
            return _fail(f'/full missing {cmd}')
    for cmd in ('/premarket', '/premarket full', '/action plan', '/today', '/tomorrow', '/morning'):
        if cmd in FULL_SNAPSHOT_SEQUENCE:
            return _fail(f'/full must not include legacy {cmd}')
    if FULL_SNAPSHOT_SEQUENCE.index('/catalysts today') >= FULL_SNAPSHOT_SEQUENCE.index('/tradecard'):
        return _fail('/catalysts today must precede /tradecard')
    if FULL_SNAPSHOT_SEQUENCE.index('/radar') < FULL_SNAPSHOT_SEQUENCE.index('/catalysts today'):
        return _fail('/radar must follow /catalysts today')
    print('FULL_INCLUDES_CATALYSTS_TRADECARD_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
