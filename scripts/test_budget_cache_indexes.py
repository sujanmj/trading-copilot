#!/usr/bin/env python3
"""Unit tests for budget cache indexes (Stage 48G)."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.analytics.budget_impact import ensure_cache_indexes


def _fail(msg: str) -> int:
    print(f'BUDGET_CACHE_INDEXES_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    legacy = {
        'ok': True,
        'freshness': {'status': 'partial'},
        'top_catalysts': [{
            'theme_id': 'roads_highways',
            'display_name': 'Roads / Highways',
            'headline': 'Govt announces ₹11000 crore highway project in Bengaluru',
        }],
    }
    out = ensure_cache_indexes(dict(legacy))
    for key in ('themes_by_id', 'catalysts_by_id', 'catalysts_by_theme', 'scan_by_theme', 'drilldown_by_catalyst'):
        if key not in out:
            return _fail(f'missing derived index {key!r}')
    if 'roads_highways' not in out['themes_by_id']:
        return _fail('derived themes_by_id must include roads_highways')
    if not out['drilldown_by_catalyst']:
        return _fail('derived drilldown_by_catalyst must not be empty')

    bi_src = (PROJECT_ROOT / 'backend/analytics/budget_impact.py').read_text(encoding='utf-8')
    for needle in ('themes_by_id', 'catalysts_by_id', 'drilldown_by_catalyst', 'ensure_cache_indexes'):
        if needle not in bi_src:
            return _fail(f'budget_impact.py missing {needle!r}')

    print('BUDGET_CACHE_INDEXES_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
