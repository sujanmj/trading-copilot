#!/usr/bin/env python3
"""Validate Telegram AIHub typo aliases (Stage 48J)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
os.chdir(PROJECT_ROOT)


def _fail(msg: str) -> int:
    print(f'TELEGRAM_AIHUB_TYPO_ALIASES_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    norm = (PROJECT_ROOT / 'backend/telegram/telegram_command_normalize.py').read_text(encoding='utf-8')
    bot = (PROJECT_ROOT / 'backend/telegram/telegram_analysis_bot.py').read_text(encoding='utf-8')
    for needle in ('AIHUB_TAB_TYPO_ALIASES', 'normalize_aihub_tab', 'format_unknown_aihub_tab'):
        if needle not in norm and needle not in bot:
            return _fail(f'missing {needle!r}')
    if "'callib': 'calib'" not in norm:
        return _fail('callib typo alias missing')
    if os.system(f'{sys.executable} scripts/test_telegram_aihub_typo_aliases.py') != 0:
        return _fail('test_telegram_aihub_typo_aliases.py failed')
    print('TELEGRAM_AIHUB_TYPO_ALIASES_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
