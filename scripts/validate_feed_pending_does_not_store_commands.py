#!/usr/bin/env python3
"""Validate pending mode must not store slash commands as feed (Stage 50C)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    rc = subprocess.call([sys.executable, str(PROJECT_ROOT / 'scripts/test_feed_pending_does_not_store_commands.py')])
    if rc != 0:
        return rc
    print('FEED_PENDING_DOES_NOT_STORE_COMMANDS_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
