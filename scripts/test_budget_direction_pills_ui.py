#!/usr/bin/env python3
"""Unit tests for budget direction pills UI (Stage 48I)."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _fail(msg: str) -> int:
    print(f'BUDGET_DIRECTION_PILLS_UI_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    index_html = (PROJECT_ROOT / 'frontend/index.html').read_text(encoding='utf-8')
    panel_js = (PROJECT_ROOT / 'frontend/components/BudgetImpactPanel.js').read_text(encoding='utf-8')

    for needle in (
        '.bud-dir-pill',
        '.bud-dir-positive',
        '.bud-dir-negative',
        '.bud-dir-neutral',
        '.bud-dir-mixed',
    ):
        if needle not in index_html:
            return _fail(f'index.html missing direction pill CSS {needle!r}')

    for needle in (
        'catalystDirectionPill',
        'catalystDirectionClass',
        'formatCatalystDirection',
        'bud-dir-pill',
        'bud-dir-positive',
        'bud-dir-negative',
        'bud-dir-neutral',
        'bud-dir-mixed',
    ):
        if needle not in panel_js:
            return _fail(f'BudgetImpactPanel.js missing direction pill marker {needle!r}')

    if "Direction ?" in panel_js or "Direction ${escapeHtml(cat.catalyst_direction" in panel_js:
        return _fail('BudgetImpactPanel must not render raw Direction ? text')

    cls_block = panel_js.split('function catalystDirectionClass')[1].split('function catalystDirectionPill')[0]
    for label in ('positive', 'negative', 'neutral', 'mixed'):
        if label not in cls_block:
            return _fail(f'direction pill classes must support {label!r}')

    print('BUDGET_DIRECTION_PILLS_UI_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
