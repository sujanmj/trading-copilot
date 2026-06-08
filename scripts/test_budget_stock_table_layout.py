#!/usr/bin/env python3
"""Unit tests for budget stock table layout below catalyst news (Stage 48I)."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _fail(msg: str) -> int:
    print(f'BUDGET_STOCK_TABLE_LAYOUT_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    index_html = (PROJECT_ROOT / 'frontend/index.html').read_text(encoding='utf-8')
    panel_js = (PROJECT_ROOT / 'frontend/components/BudgetImpactPanel.js').read_text(encoding='utf-8')

    for needle in (
        '.bud-table-wrap',
        'overflow-x: auto',
        '.bud-stocks-block',
        '.bud-stock-section',
        '.bud-section-subtitle',
        'min-width: 720px',
    ):
        if needle not in index_html:
            return _fail(f'index.html missing stock table layout CSS {needle!r}')

    for label in (
        'Investment Watch',
        'Indirect Watch',
        'Avoid / Risk',
        'Wait for Confirmation',
        'Research Only',
    ):
        if label not in panel_js:
            return _fail(f'BudgetImpactPanel.js missing section header {label!r}')

    for needle in (
        'bud-table-wrap',
        'bud-stock-section',
        'bud-stocks-block',
        'bud-section-subtitle',
        'renderStockTable',
    ):
        if needle not in panel_js:
            return _fail(f'BudgetImpactPanel.js missing {needle!r}')

    render_block = panel_js.split('function renderDashboard')[1].split('function wireEvents')[0]
    if render_block.find('bud-catalyst-block') > render_block.find('bud-stocks-block'):
        return _fail('stock ranking block must follow catalyst block in render order')

    print('BUDGET_STOCK_TABLE_LAYOUT_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
