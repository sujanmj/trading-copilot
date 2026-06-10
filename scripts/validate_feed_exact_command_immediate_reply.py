#!/usr/bin/env python3
"""Validate /feed immediate pending reply (Stage 50C)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    rc = subprocess.call([sys.executable, str(PROJECT_ROOT / 'scripts/test_feed_exact_command_immediate_reply.py')])
    if rc != 0:
        return rc
    print('FEED_EXACT_COMMAND_IMMEDIATE_REPLY_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
