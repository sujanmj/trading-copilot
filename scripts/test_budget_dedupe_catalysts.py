#!/usr/bin/env python3
"""Unit tests for budget catalyst dedupe (Stage 48F)."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.analytics.budget_impact import dedupe_catalyst_rows


def _fail(msg: str) -> int:
    print(f'BUDGET_DEDUPE_CATALYSTS_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    rows = [
        {'headline': 'Tata Steel UK project delayed'},
        {'headline': 'Tata Steel UK project delayed!'},
        {'headline': 'Govt announces highway project in Bengaluru'},
    ]
    out = dedupe_catalyst_rows(rows)
    tata = [r for r in out if 'tata steel' in str(r.get('headline', '')).lower()]
    if len(tata) != 1:
        return _fail('duplicate Tata Steel headlines must collapse to one')
    if len(out) != 2:
        return _fail('dedupe must keep distinct headlines')
    print('BUDGET_DEDUPE_CATALYSTS_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
