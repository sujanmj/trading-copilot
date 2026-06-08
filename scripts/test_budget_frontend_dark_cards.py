#!/usr/bin/env python3
"""Unit tests for budget frontend dark catalyst cards (Stage 48I)."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _fail(msg: str) -> int:
    print(f'BUDGET_FRONTEND_DARK_CARDS_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    index_html = (PROJECT_ROOT / 'frontend/index.html').read_text(encoding='utf-8')
    panel_js = (PROJECT_ROOT / 'frontend/components/BudgetImpactPanel.js').read_text(encoding='utf-8')

    for needle in (
        '.bud-catalyst-btn',
        'background: #111820',
        '.bud-catalyst-btn:hover',
        '.bud-catalyst-btn.active',
        '.bud-catalyst-headline',
        '.bud-catalyst-why',
        'color: #5eb8ff',
        '.bud-catalyst-scores',
    ):
        if needle not in index_html:
            return _fail(f'index.html missing dark card CSS {needle!r}')

    for bad in ('background: #fff', 'background:#fff', 'background: white', 'background:white'):
        catalyst_css = index_html.split('.bud-catalyst-btn')[1].split('.bud-catalyst-row')[0]
        if bad in catalyst_css.lower():
            return _fail(f'catalyst card CSS must not use light background {bad!r}')

    for needle in (
        'bud-catalyst-btn',
        'bud-catalyst-list',
        'bud-catalyst-why',
        'catalystDirectionPill',
        'formatCatalystDirection',
    ):
        if needle not in panel_js:
            return _fail(f'BudgetImpactPanel.js missing {needle!r}')

    if 'background: #fff' in panel_js or 'background:#fff' in panel_js:
        return _fail('BudgetImpactPanel.js must not inline white card backgrounds')

    print('BUDGET_FRONTEND_DARK_CARDS_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
