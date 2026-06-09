#!/usr/bin/env python3
"""Validate /resolve outcomes admin command (Stage 49D)."""

from __future__ import annotations

import os
import sys


def main() -> int:
    if os.system(f'{sys.executable} scripts/test_telegram_resolve_outcomes_admin_command.py') != 0:
        return 1
    print('TELEGRAM_RESOLVE_OUTCOMES_ADMIN_COMMAND_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
