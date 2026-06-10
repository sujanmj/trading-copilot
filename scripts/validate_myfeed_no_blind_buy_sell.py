#!/usr/bin/env python3
"""Validate My Feed never blind BUY/SELL (Stage 50B)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    rc = subprocess.call([sys.executable, str(PROJECT_ROOT / 'scripts/test_myfeed_no_blind_buy_sell.py')])
    if rc != 0:
        return rc
    print('MYFEED_NO_BLIND_BUY_SELL_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
