#!/usr/bin/env python3
"""Unit tests for Telegram AIHub typo aliases (Stage 48J)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

os.environ.setdefault('DISABLE_TELEGRAM', '1')
os.environ.setdefault('DISABLE_TELEGRAM_SENDS', '1')


def _fail(msg: str) -> int:
    print(f'TELEGRAM_AIHUB_TYPO_ALIASES_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.telegram.telegram_command_normalize import normalize_aihub_tab
    from backend.telegram.telegram_analysis_bot import _handle_aihub

    for typo, canonical in (
        ('callib', 'calib'),
        ('calibb', 'calib'),
        ('calibration', 'calib'),
        ('calibrate', 'calib'),
        ('journals', 'journal'),
        ('markets', 'market'),
    ):
        if normalize_aihub_tab(typo) != canonical:
            return _fail(f'{typo} should normalize to {canonical}')

    text = _handle_aihub('callib')
    if 'Unknown AI Hub tab' in text and 'Examples:' not in text:
        return _fail('callib should dispatch or show friendly menu')
    if 'AI Hub' not in text:
        return _fail('callib response missing AI Hub')

    unknown = _handle_aihub('notarealtab')
    if 'Unknown AI Hub tab' not in unknown:
        return _fail('unknown tab must be labeled')
    if 'Examples:' not in unknown:
        return _fail('unknown tab must include examples')

    print('TELEGRAM_AIHUB_TYPO_ALIASES_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
