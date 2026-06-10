#!/usr/bin/env python3
"""Unit tests — Reddit removed fully (Stage 50A hotfix alias)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    legacy = subprocess.call([sys.executable, str(PROJECT_ROOT / 'scripts/test_reddit_removed_fully.py')])
    if legacy != 0:
        print('REMOVE_REDDIT_FULLY_TEST_FAIL: reddit removal gate failed', file=sys.stderr)
        return legacy
    print('REMOVE_REDDIT_FULLY_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
