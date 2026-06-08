#!/usr/bin/env python3
"""Unit tests ensuring budget catalyst list never shows Direction ? (Stage 48H)."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.analytics.budget_impact import enrich_catalyst_row, get_budget_overview, get_budget_theme_news


def _fail(msg: str) -> int:
    print(f'BUDGET_CATALYST_LIST_NO_QUESTION_MARK_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    panel_path = PROJECT_ROOT / 'frontend' / 'components' / 'BudgetImpactPanel.js'
    panel_src = panel_path.read_text(encoding='utf-8')
    if "catalyst_direction || '?'" in panel_src:
        return _fail('BudgetImpactPanel.js still renders Direction ? fallback')
    if 'formatCatalystDirection' not in panel_src:
        return _fail('BudgetImpactPanel.js missing formatCatalystDirection helper')

    row = enrich_catalyst_row({'headline': 'Sector outlook update from brokerage'})
    if row.get('catalyst_direction') in ('', '?', None):
        return _fail('enrich must never leave direction empty or ?')

    overview = get_budget_overview(cache_only=True, lite=True)
    for cat in overview.get('top_catalysts') or []:
        if str(cat.get('catalyst_direction') or '').strip() in ('', '?'):
            return _fail(f'overview catalyst direction invalid: {cat!r}')

    news = get_budget_theme_news('infrastructure', cache_only=True, lite=True)
    if news.get('ok'):
        for cat in news.get('catalysts') or []:
            if str(cat.get('catalyst_direction') or '').strip() in ('', '?'):
                return _fail(f'theme news catalyst direction invalid: {cat!r}')

    print('BUDGET_CATALYST_LIST_NO_QUESTION_MARK_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
