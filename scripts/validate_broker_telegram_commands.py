#!/usr/bin/env python3
"""Validate broker Telegram commands (Stage 48L)."""

from __future__ import annotations

import os
import sys


def main() -> int:
    if os.system(f'{sys.executable} scripts/test_broker_telegram_commands.py') != 0:
        print('BROKER_TELEGRAM_COMMANDS_FAIL: test failed', file=sys.stderr)
        return 1
    print('BROKER_TELEGRAM_COMMANDS_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
