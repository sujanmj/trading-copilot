#!/usr/bin/env python3
"""Unit tests for theme-specific budget scan (Stage 48G)."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.analytics.budget_impact import get_budget_theme_scan, rank_stocks_for_catalyst


def _fail(msg: str) -> int:
    print(f'BUDGET_THEME_SPECIFIC_SCAN_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    hi = 'Govt announces ₹11000 crore highway project in Bengaluru'
    ranked = rank_stocks_for_catalyst(hi, 'roads_highways', freshness={'status': 'partial'})
    direct = {r['ticker'] for r in ranked['sections']['positive_investment_watch']}
    if not {'HGINFRA', 'IRB', 'PNCINFRA'}.issubset(direct):
        return _fail('roads/highways scan must include infra direct beneficiaries')

    delay = 'Tata Steel UK project delayed by 8 months'
    neg = rank_stocks_for_catalyst(delay, 'infrastructure', freshness={'status': 'partial'})
    if neg['sections']['positive_investment_watch']:
        return _fail('negative catalyst must not populate positive section for infrastructure theme')

    cached = {'ok': True, 'freshness': {'status': 'partial'}, 'top_catalysts': []}
    with patch('backend.analytics.budget_impact._load_cache', return_value=cached):
        with patch('backend.analytics.theme_baskets.get_basket_by_id', return_value={'theme_id': 'roads_highways'}):
            out = get_budget_theme_scan('roads_highways', cache_only=True, lite=True)
    if not out.get('ok'):
        return _fail('lite theme scan must return ok JSON')
    if 'sections' not in out:
        return _fail('lite theme scan must include sections')

    print('BUDGET_THEME_SPECIFIC_SCAN_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
