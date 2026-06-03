#!/usr/bin/env python3
"""Validate EOD outcome scoring pack (Stage 46G)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _fail(msg: str) -> int:
    print(f'EOD_OUTCOME_SCORING_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    path = PROJECT_ROOT / 'backend/analytics/eod_outcome_scoring.py'
    if not path.is_file():
        return _fail('missing eod_outcome_scoring.py')

    src = path.read_text(encoding='utf-8')
    for needle in ('WIN', 'LOSS', 'NEUTRAL', 'PARTIAL', 'EXPIRED', 'format_eod_telegram_message'):
        if needle not in src:
            return _fail(f'missing {needle} in eod_outcome_scoring')

    proc = subprocess.run([sys.executable, 'scripts/test_eod_outcome_scoring.py'], cwd=PROJECT_ROOT)
    if proc.returncode != 0:
        return _fail('test_eod_outcome_scoring.py failed')

    print('EOD_OUTCOME_SCORING_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
