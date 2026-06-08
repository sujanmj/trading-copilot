#!/usr/bin/env python3
"""Validate Telegram budget aliases (Stage 48J)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
os.chdir(PROJECT_ROOT)


def _fail(msg: str) -> int:
    print(f'TELEGRAM_BUDGET_ALIASES_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    budget = (PROJECT_ROOT / 'backend/analytics/budget_impact.py').read_text(encoding='utf-8')
    norm = (PROJECT_ROOT / 'backend/telegram/telegram_command_normalize.py').read_text(encoding='utf-8')
    for needle in ("sub == 'overview'", 'format_budget_theme_usage', 'format_budget_analyze_usage'):
        if needle not in budget and needle not in norm:
            return _fail(f'missing {needle!r}')
    if os.system(f'{sys.executable} scripts/test_telegram_budget_aliases.py') != 0:
        return _fail('test_telegram_budget_aliases.py failed')
    print('TELEGRAM_BUDGET_ALIASES_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
