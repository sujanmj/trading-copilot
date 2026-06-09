#!/usr/bin/env python3
"""Validate missing broker ticker suggestions (Stage 48N)."""

from __future__ import annotations

import os
import sys


def main() -> int:
    if os.system(f'{sys.executable} scripts/test_broker_missing_ticker_suggestions.py') != 0:
        return 1
    print('BROKER_MISSING_TICKER_SUGGESTIONS_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
