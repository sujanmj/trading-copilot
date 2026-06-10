#!/usr/bin/env python3
"""Validate Reddit fully removed (Stage 50A)."""

from __future__ import annotations

import os
import sys


def main() -> int:
    if os.system(f'{sys.executable} scripts/test_reddit_removed_fully.py') != 0:
        return 1
    print('REDDIT_REMOVED_FULLY_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
