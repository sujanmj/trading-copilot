#!/usr/bin/env python3
"""Validate Telegram theme reserved words (Stage 48J)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
os.chdir(PROJECT_ROOT)


def _fail(msg: str) -> int:
    print(f'TELEGRAM_THEME_RESERVED_WORDS_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    norm = (PROJECT_ROOT / 'backend/telegram/telegram_command_normalize.py').read_text(encoding='utf-8')
    theme = (PROJECT_ROOT / 'backend/analytics/theme_baskets.py').read_text(encoding='utf-8')
    for needle in ('THEME_RESERVED_WORDS', 'format_theme_search_usage', "sub == 'overview'"):
        if needle not in norm and needle not in theme:
            return _fail(f'missing {needle!r}')
    if os.system(f'{sys.executable} scripts/test_telegram_theme_reserved_words.py') != 0:
        return _fail('test_telegram_theme_reserved_words.py failed')
    print('TELEGRAM_THEME_RESERVED_WORDS_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
