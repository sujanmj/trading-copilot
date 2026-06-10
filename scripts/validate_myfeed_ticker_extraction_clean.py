#!/usr/bin/env python3
"""Validate clean My Feed ticker extraction (Stage 50C)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    rc = subprocess.call([sys.executable, str(PROJECT_ROOT / 'scripts/test_myfeed_ticker_extraction_clean.py')])
    if rc != 0:
        return rc
    print('MYFEED_TICKER_EXTRACTION_CLEAN_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
