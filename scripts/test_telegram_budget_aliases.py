#!/usr/bin/env python3
"""Unit tests for Telegram budget aliases (Stage 48J)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)


def _fail(msg: str) -> int:
    print(f'TELEGRAM_BUDGET_ALIASES_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.analytics.budget_impact import handle_budget_command

    overview = handle_budget_command('')
    if 'Budget Impact' not in overview:
        return _fail('empty budget must show overview')

    overview2 = handle_budget_command('overview')
    if 'Budget Impact' not in overview2:
        return _fail('budget overview must show overview')

    theme_usage = handle_budget_command('theme')
    if 'budget theme' not in theme_usage.lower():
        return _fail('budget theme without basket must show usage')

    analyze_usage = handle_budget_command('analyze')
    if 'budget analyze' not in analyze_usage.lower():
        return _fail('budget analyze without text must show usage')

    print('TELEGRAM_BUDGET_ALIASES_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
