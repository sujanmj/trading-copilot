#!/usr/bin/env python3
"""Unit tests for budget theme click drilldown (Stage 48G)."""

from __future__ import annotations

import sys
from pathlib import Path

PANEL = Path(__file__).resolve().parent.parent / 'frontend' / 'components' / 'BudgetImpactPanel.js'


def _fail(msg: str) -> int:
    print(f'BUDGET_THEME_CLICK_DRILLDOWN_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    src = PANEL.read_text(encoding='utf-8')
    for needle in (
        'selectedThemeId',
        'selectedThemeName',
        'themeLitePath',
        'newsLitePath',
        'scanLitePath',
        'cache_only=1&lite=1',
        'bud-theme-chip${active}',
        'Clear Theme',
        'loadThemeDetail',
    ):
        if needle not in src:
            return _fail(f'BudgetImpactPanel.js missing {needle!r}')
    if '/api/budget/refresh' not in src.split('loadThemeDetail')[1].split('refreshBudget')[0]:
        pass
    load_block = src.split('async function loadThemeDetail')[1].split('async function loadCatalystDrilldown')[0]
    if '/api/budget/theme/' in load_block and 'cache_only=1' not in load_block:
        return _fail('theme click must use cache_only lite endpoints')
    if 'refreshBudget' in load_block:
        return _fail('theme click must not call refreshBudget')
    print('BUDGET_THEME_CLICK_DRILLDOWN_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
