#!/usr/bin/env python3
"""Validate memory/calib outcome warnings (Stage 48Q)."""

from __future__ import annotations

import os
import sys


def main() -> int:
    if os.system(f'{sys.executable} scripts/test_memory_outcome_warning.py') != 0:
        return 1
    print('MEMORY_OUTCOME_WARNING_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
