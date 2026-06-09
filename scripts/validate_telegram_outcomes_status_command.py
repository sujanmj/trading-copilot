#!/usr/bin/env python3
"""Validate /outcomes Telegram command (Stage 49D)."""

from __future__ import annotations

import os
import sys


def main() -> int:
    if os.system(f'{sys.executable} scripts/test_telegram_outcomes_status_command.py') != 0:
        return 1
    print('TELEGRAM_OUTCOMES_STATUS_COMMAND_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
