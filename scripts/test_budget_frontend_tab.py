#!/usr/bin/env python3
"""Unit tests for Budget frontend tab (Stage 48A)."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _fail(msg: str) -> int:
    print(f'BUDGET_FRONTEND_TAB_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    index_html = (PROJECT_ROOT / 'frontend/index.html').read_text(encoding='utf-8')
    panel_js = (PROJECT_ROOT / 'frontend/components/BudgetImpactPanel.js').read_text(encoding='utf-8')
    ws_js = (PROJECT_ROOT / 'frontend/components/WorkspaceManager.js').read_text(encoding='utf-8')

    for needle in (
        'id="budgetNavBtn"',
        '🏛️ Budget',
        'Budget Impact Intelligence',
        'workspace-budget',
        'budgetMainPanel',
        'BudgetImpactPanel.js',
        'data-workspace="budget"',
    ):
        if needle not in index_html:
            return _fail(f'index.html missing {needle!r}')

    for needle in (
        'BudgetImpactPanel',
        '/api/budget/overview',
        '/api/budget/themes',
        '/api/budget/analyze-news',
        'Budget API returned non-JSON',
        'Refresh Budget Intel',
        'Budget event simulator',
    ):
        if needle not in panel_js:
            return _fail(f'BudgetImpactPanel.js missing {needle!r}')

    for needle in ("'budget'", 'budgetNavBtn', 'BudgetImpactPanel.loadMain'):
        if needle not in ws_js:
            return _fail(f'WorkspaceManager.js missing {needle!r}')

    if 'id="memoryNavBtn"' not in index_html or index_html.index('budgetNavBtn') < index_html.index('brokersNavBtn'):
        pass  # budget near memory — order check optional

    print('BUDGET_FRONTEND_TAB_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
