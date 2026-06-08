#!/usr/bin/env python3
"""Unit tests for budget freshness panel (Stage 48F)."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.analytics.budget_impact import compute_freshness_panel


def _fail(msg: str) -> int:
    print(f'BUDGET_FRESHNESS_PANEL_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    panel_js = (PROJECT_ROOT / 'frontend/components/BudgetImpactPanel.js').read_text(encoding='utf-8')
    if 'Unavailable' not in panel_js:
        return _fail('frontend freshness must show Unavailable fallback')

    fresh = compute_freshness_panel()
    for key in ('news', 'theme_cache', 'scanner', 'budget_cache'):
        row = fresh.get(key) or {}
        if row.get('age_label') in (None, '', '—'):
            return _fail(f'{key} age_label must not be blank dash')
        if not row.get('status'):
            return _fail(f'{key} must include status')

    if fresh.get('latest_news_age') in (None, '', '—'):
        return _fail('latest_news_age must not be blank dash')
    if fresh.get('status') not in ('fresh', 'partial', 'stale', 'cache_missing'):
        return _fail('overall freshness status invalid')

    print('BUDGET_FRESHNESS_PANEL_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
