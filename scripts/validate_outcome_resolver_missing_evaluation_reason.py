#!/usr/bin/env python3
"""Validate resolver missing_evaluation skip reason (Stage 49C)."""

from __future__ import annotations

import os
import sys


def main() -> int:
    if os.system(f'{sys.executable} scripts/test_outcome_resolver_missing_evaluation_reason.py') != 0:
        return 1
    print('OUTCOME_RESOLVER_MISSING_EVALUATION_REASON_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
