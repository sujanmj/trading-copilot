#!/usr/bin/env python3
"""Validate no fake outcomes without price data (Stage 49A)."""

from __future__ import annotations

import os
import sys


def main() -> int:
    if os.system(f'{sys.executable} scripts/test_outcome_resolver_no_fake_without_price.py') != 0:
        return 1
    print('OUTCOME_RESOLVER_NO_FAKE_WITHOUT_PRICE_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
