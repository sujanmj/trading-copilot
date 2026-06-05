#!/usr/bin/env python3
"""Validate /memory outcome clarity pack (Stage 46J)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)


def _fail(msg: str) -> int:
    print(f'MEMORY_OUTCOME_CLARITY_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    runner_src = (PROJECT_ROOT / 'backend/telegram/lazy_command_runner.py').read_text(encoding='utf-8')
    for needle in (
        'Predictions tracked:',
        'Outcomes resolved: 0',
        'Pending resolution:',
        'awaiting close-price/outcome resolver or next market session',
        'Source: cloud/runtime cache',
    ):
        if needle not in runner_src:
            return _fail(f'lazy_command_runner missing {needle}')

    proc = os.system(f'{sys.executable} scripts/test_memory_outcome_clarity.py')
    if proc != 0:
        return _fail('test_memory_outcome_clarity.py failed')

    print('MEMORY_OUTCOME_CLARITY_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
