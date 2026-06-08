#!/usr/bin/env python3
"""Unit tests for Budget cache-first load (Stage 48A/48C/48D)."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
PANEL = PROJECT_ROOT / 'frontend/components/BudgetImpactPanel.js'


def _fail(msg: str) -> int:
    print(f'BUDGET_CACHE_FIRST_LOAD_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    panel = PANEL.read_text(encoding='utf-8')

    for needle in (
        'cache_only=1&lite=1',
        'themes?lite=1',
        'Budget cache unavailable',
        'Budget cache request timed out',
        'Budget refresh may still be running',
        'renderBudgetShell',
    ):
        if needle not in panel:
            return _fail(f'BudgetImpactPanel.js missing {needle!r}')

    if '/api/budget/refresh' not in panel:
        return _fail('refresh endpoint missing')

    print('BUDGET_CACHE_FIRST_LOAD_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
