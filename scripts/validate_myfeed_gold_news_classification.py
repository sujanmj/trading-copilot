#!/usr/bin/env python3
"""Validate gold commodity news classification (Stage 50C)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    rc = subprocess.call([sys.executable, str(PROJECT_ROOT / 'scripts/test_myfeed_gold_news_classification.py')])
    if rc != 0:
        return rc
    print('MYFEED_GOLD_NEWS_CLASSIFICATION_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
