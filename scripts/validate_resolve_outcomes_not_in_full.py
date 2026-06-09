#!/usr/bin/env python3
"""Validate /resolve outcomes not in /full (Stage 49D)."""

from __future__ import annotations

import os
import sys


def main() -> int:
    if os.system(f'{sys.executable} scripts/test_resolve_outcomes_not_in_full.py') != 0:
        return 1
    print('RESOLVE_OUTCOMES_NOT_IN_FULL_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
