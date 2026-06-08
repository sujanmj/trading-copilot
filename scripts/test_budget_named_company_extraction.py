#!/usr/bin/env python3
"""Unit tests for budget named company extraction (Stage 48F)."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.analytics.budget_impact import extract_named_companies_strict
from backend.analytics.theme_baskets import _find_named_companies, get_basket_by_id


def _fail(msg: str) -> int:
    print(f'BUDGET_NAMED_COMPANY_EXTRACTION_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    headline = 'According to sources, Tata Steel UK project delayed again'
    named = extract_named_companies_strict(headline)
    if 'ACC' in named:
        return _fail('ACC must not be named in Tata Steel headline')
    if 'TATASTEEL' not in named:
        return _fail('TATASTEEL must be named in Tata Steel headline')

    basket = get_basket_by_id('roads_highways') or {}
    legacy = _find_named_companies(headline, basket)
    if 'ACC' in legacy:
        return _fail('word-boundary fix must prevent ACC from according-substring match')

    print('BUDGET_NAMED_COMPANY_EXTRACTION_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
