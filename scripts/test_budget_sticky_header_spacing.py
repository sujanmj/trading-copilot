#!/usr/bin/env python3
"""Unit tests for budget sticky header spacing (Stage 48I)."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _fail(msg: str) -> int:
    print(f'BUDGET_STICKY_HEADER_SPACING_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    index_html = (PROJECT_ROOT / 'frontend/index.html').read_text(encoding='utf-8')
    panel_js = (PROJECT_ROOT / 'frontend/components/BudgetImpactPanel.js').read_text(encoding='utf-8')

    panel_css = index_html.split('.budget-main-panel')[1].split('.bud-dashboard')[0]
    for needle in ('padding:', 'scroll-padding-top'):
        if needle not in panel_css:
            return _fail(f'budget-main-panel CSS missing spacing rule {needle!r}')

    for needle in (
        '.bud-selection-bar',
        '.bud-selection-row',
        '.bud-selection-actions',
        'bud-selection-bar',
        'Selected theme:',
        'Selected catalyst:',
    ):
        if needle not in index_html and needle not in panel_js:
            return _fail(f'missing selection bar spacing marker {needle!r}')

    if 'bud-dashboard' not in panel_js or 'renderSelectionBar' not in panel_js:
        return _fail('BudgetImpactPanel must render selection bar inside dashboard')

    print('BUDGET_STICKY_HEADER_SPACING_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
