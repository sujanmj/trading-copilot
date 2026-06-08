#!/usr/bin/env python3
"""Unit tests for budget catalyst drilldown (Stage 48G)."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

PANEL = PROJECT_ROOT / 'frontend' / 'components' / 'BudgetImpactPanel.js'


def _fail(msg: str) -> int:
    print(f'BUDGET_CATALYST_DRILLDOWN_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    src = PANEL.read_text(encoding='utf-8')
    for needle in (
        'selectedCatalystId',
        'catalystDrilldown',
        'loadCatalystDrilldown',
        'renderCatalystDrilldown',
        'Catalyst impact drilldown',
        'Clear Catalyst',
        'catalystLitePath',
    ):
        if needle not in src:
            return _fail(f'BudgetImpactPanel.js missing {needle!r}')

    from backend.analytics import budget_impact as bi

    headline = 'Tata Steel UK project delayed by 8 months'
    tid = 'cement_steel_paint'
    cid = bi._make_catalyst_id(tid, headline)
    cached = {
        'ok': True,
        'freshness': {'status': 'partial'},
        'top_catalysts': [{
            'theme_id': tid,
            'headline': headline,
            'display_name': 'Cement / Steel / Paint',
        }],
    }
    with patch('backend.analytics.budget_impact._load_cache', return_value=cached):
        drill = bi.get_budget_catalyst_drilldown(cid, cache_only=True, lite=True)
    if not drill.get('ok'):
        return _fail('catalyst drilldown must return ok from derived cache')
    if drill.get('direction') != 'Negative':
        return _fail('delay catalyst must be Negative')
    avoid = {r.get('ticker') for r in (drill.get('avoid_risk') or [])}
    if 'TATASTEEL' not in avoid:
        return _fail('TATASTEEL must be Avoid/Risk in catalyst drilldown')

    hi = 'Govt announces ₹11000 crore highway project in Bengaluru'
    hi_drill = bi._build_catalyst_drilldown_payload(
        {'headline': hi, 'theme_id': 'roads_highways', 'catalyst_id': bi._make_catalyst_id('roads_highways', hi)},
        freshness={'status': 'partial'},
        theme_id='roads_highways',
    )
    direct = {r.get('ticker') for r in (hi_drill.get('direct_beneficiaries') or [])}
    for ticker in ('HGINFRA', 'IRB', 'PNCINFRA'):
        if ticker not in direct:
            return _fail(f'{ticker} must be direct beneficiary for highway catalyst')

    print('BUDGET_CATALYST_DRILLDOWN_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
