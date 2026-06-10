#!/usr/bin/env python3
"""Validate Telegram feed command aliases (Stage 50B)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    rc = subprocess.call([sys.executable, str(PROJECT_ROOT / 'scripts/test_telegram_feed_aliases.py')])
    if rc != 0:
        return rc
    print('TELEGRAM_FEED_ALIASES_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
