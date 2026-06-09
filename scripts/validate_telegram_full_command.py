#!/usr/bin/env python3
"""Validate /full Telegram command (Stage 48P)."""

from __future__ import annotations

import os
import sys


def main() -> int:
    if os.system(f'{sys.executable} scripts/test_telegram_full_command.py') != 0:
        return 1
    print('TELEGRAM_FULL_COMMAND_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
