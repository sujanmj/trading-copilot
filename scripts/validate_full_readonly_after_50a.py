#!/usr/bin/env python3
"""Validate /full read-only after Stage 50A."""

from __future__ import annotations

import os
import sys


def main() -> int:
    if os.system(f'{sys.executable} scripts/test_full_readonly_after_50a.py') != 0:
        return 1
    print('FULL_READONLY_AFTER_50A_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
