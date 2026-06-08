#!/usr/bin/env python3
"""Unit tests for Budget fetch abort handling (Stage 48B/48D)."""

from __future__ import annotations

import sys
from pathlib import Path

PANEL = Path(__file__).resolve().parent.parent / 'frontend/components/BudgetImpactPanel.js'


def _fail(msg: str) -> int:
    print(f'BUDGET_FETCH_ABORT_HANDLING_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    src = PANEL.read_text(encoding='utf-8')
    forbidden = ('signal is aborted without reason', 'Budget request timed out or was cancelled')
    for needle in forbidden:
        if needle in src:
            return _fail(f'must not expose {needle!r}')
    for needle in (
        'Budget cache request timed out',
        'loadGeneration',
        'abortActiveRequest',
        'OVERVIEW_LITE_PATH',
    ):
        if needle not in src:
            return _fail(f'missing {needle!r}')
    print('BUDGET_FETCH_ABORT_HANDLING_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
