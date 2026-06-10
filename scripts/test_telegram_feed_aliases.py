#!/usr/bin/env python3
"""Unit tests — legacy alias validate redirects to single /feed (Stage 50B final)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def main() -> int:
    rc = subprocess.call([sys.executable, str(PROJECT_ROOT / 'scripts/test_telegram_feed_single_command.py')])
    if rc != 0:
        return rc
    print('TELEGRAM_FEED_ALIASES_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
