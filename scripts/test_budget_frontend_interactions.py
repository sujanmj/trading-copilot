#!/usr/bin/env python3
"""Unit tests for budget frontend interactions (Stage 48G)."""

from __future__ import annotations

import sys
from pathlib import Path

PANEL = Path(__file__).resolve().parent.parent / 'frontend' / 'components' / 'BudgetImpactPanel.js'


def _fail(msg: str) -> int:
    print(f'BUDGET_FRONTEND_INTERACTIONS_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    src = PANEL.read_text(encoding='utf-8')
    for needle in (
        'bud-catalyst-btn',
        'data-catalyst-id',
        'Selected theme:',
        'Selected catalyst:',
        'clearTheme',
        'clearCatalyst',
        'Stock ranking — selected catalyst impact',
        'Stock ranking — top overall budget impact',
    ):
        if needle not in src:
            return _fail(f'missing interaction marker {needle!r}')

    catalyst_block = src.split('async function loadCatalystDrilldown')[1].split('async function refreshBudget')[0]
    if '/api/budget/refresh' in catalyst_block:
        return _fail('catalyst click must not call refresh endpoint')
    if 'get_theme_catalysts' in catalyst_block:
        return _fail('catalyst click must not reference heavy backend symbols')

    print('BUDGET_FRONTEND_INTERACTIONS_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
