#!/usr/bin/env python3
"""Unit tests for budget stock ranking sections (Stage 48F)."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.analytics.budget_impact import STOCK_SECTION_LABELS, rank_stocks_for_catalyst


def _fail(msg: str) -> int:
    print(f'BUDGET_STOCK_RANKING_SECTIONS_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    panel = (PROJECT_ROOT / 'frontend/components/BudgetImpactPanel.js').read_text(encoding='utf-8')
    for label in STOCK_SECTION_LABELS.values():
        if label not in panel:
            return _fail(f'BudgetImpactPanel missing section label {label!r}')

    hi = rank_stocks_for_catalyst(
        'Govt announces ₹11,000 crore highway project in Bengaluru',
        'roads_highways',
    )
    if not hi['sections'].get('positive_investment_watch'):
        return _fail('positive section required for highway catalyst')
    if not hi['sections'].get('indirect_watch'):
        return _fail('indirect section required for highway catalyst')

    neg = rank_stocks_for_catalyst('Tata Steel UK project delayed', 'infrastructure')
    if neg['sections'].get('positive_investment_watch'):
        return _fail('negative catalyst must not populate positive section')

    print('BUDGET_STOCK_RANKING_SECTIONS_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
