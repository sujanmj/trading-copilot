#!/usr/bin/env python3
"""Validate outcome price coverage report script (Stage 49C)."""

from __future__ import annotations

import os
import sys


def main() -> int:
    if os.system(f'{sys.executable} scripts/test_outcome_price_coverage_report.py') != 0:
        return 1
    print('OUTCOME_PRICE_COVERAGE_REPORT_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
