#!/usr/bin/env python3
"""Validate budget named company extraction (Stage 48F)."""

from __future__ import annotations

import os
import sys


def main() -> int:
    if os.system(f'{sys.executable} scripts/test_budget_named_company_extraction.py') != 0:
        print('BUDGET_NAMED_COMPANY_EXTRACTION_FAIL: test failed', file=sys.stderr)
        return 1
    print('BUDGET_NAMED_COMPANY_EXTRACTION_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
