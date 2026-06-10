#!/usr/bin/env python3
"""Validate / feed typo treated as /feed (Stage 50C)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    rc = subprocess.call([sys.executable, str(PROJECT_ROOT / 'scripts/test_feed_slash_space_typo_safe.py')])
    if rc != 0:
        return rc
    print('FEED_SLASH_SPACE_TYPO_SAFE_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
