#!/usr/bin/env python3
"""Validate outcome resolver mock close prices (Stage 49A)."""

from __future__ import annotations

import os
import sys


def main() -> int:
    if os.system(f'{sys.executable} scripts/test_outcome_resolver_mock_closes.py') != 0:
        return 1
    print('OUTCOME_RESOLVER_MOCK_CLOSES_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
