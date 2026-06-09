#!/usr/bin/env python3
"""Validate /full snapshot sequence (Stage 48P)."""

from __future__ import annotations

import os
import sys


def main() -> int:
    if os.system(f'{sys.executable} scripts/test_telegram_full_sequence.py') != 0:
        return 1
    print('TELEGRAM_FULL_SEQUENCE_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
