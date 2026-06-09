#!/usr/bin/env python3
"""Validate Stage 48T /full polish suite."""

from __future__ import annotations

import os
import sys


def main() -> int:
    if os.system(f'{sys.executable} scripts/test_full_snapshot_polish_48t.py') != 0:
        return 1
    print('FULL_SNAPSHOT_POLISH_48T_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
