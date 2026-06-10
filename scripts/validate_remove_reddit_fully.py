#!/usr/bin/env python3
"""Validate Reddit removed fully (Stage 50A hotfix alias)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    rc = subprocess.call([sys.executable, str(PROJECT_ROOT / 'scripts/test_remove_reddit_fully.py')])
    if rc != 0:
        return rc
    print('REMOVE_REDDIT_FULLY_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
