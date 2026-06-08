#!/usr/bin/env python3
"""Unit tests for budget catalyst vertical layout without overlap (Stage 48I)."""

from __future__ import annotations

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _fail(msg: str) -> int:
    print(f'BUDGET_CATALYST_LAYOUT_NO_OVERLAP_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    index_html = (PROJECT_ROOT / 'frontend/index.html').read_text(encoding='utf-8')
    panel_js = (PROJECT_ROOT / 'frontend/components/BudgetImpactPanel.js').read_text(encoding='utf-8')

    layout_block = index_html.split('.bud-catalyst-list')[0] + index_html.split('.bud-catalyst-list')[1].split('.bud-catalyst-btn')[0]
    list_block = index_html.split('.bud-catalyst-list')[1].split('.bud-catalyst-btn')[0]
    btn_block = index_html.split('.bud-catalyst-btn {')[1].split('.bud-catalyst-btn:hover')[0]

    for needle in (
        'flex-direction: column',
        'width: 100%',
        'max-width: 100%',
        'box-sizing: border-box',
    ):
        if needle not in list_block:
            return _fail(f'catalyst list CSS missing {needle!r}')

    if 'position: absolute' in btn_block or 'position:absolute' in btn_block:
        return _fail('catalyst buttons must not use absolute positioning')

    if 'bud-catalyst-list' not in panel_js:
        return _fail('BudgetImpactPanel.js must wrap catalyst rows in bud-catalyst-list')
    if 'bud-right-stack' not in panel_js:
        return _fail('BudgetImpactPanel.js must use bud-right-stack column layout')
    if 'bud-catalyst-block' not in panel_js:
        return _fail('BudgetImpactPanel.js must group catalyst content in bud-catalyst-block')

    render_block = panel_js.split('function renderDashboard')[1].split('function wireEvents')[0]
    catalyst_pos = render_block.find('renderCatalystNews')
    stocks_pos = render_block.find('bud-stocks-block')
    if catalyst_pos < 0 or stocks_pos < 0 or catalyst_pos > stocks_pos:
        return _fail('catalyst news must render before stock ranking block')

    if re.search(r'position\s*:\s*absolute', panel_js, re.I):
        return _fail('BudgetImpactPanel.js must not use absolute positioning for catalyst layout')

    print('BUDGET_CATALYST_LAYOUT_NO_OVERLAP_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
