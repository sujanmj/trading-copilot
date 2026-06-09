#!/usr/bin/env python3
"""Validate natural stock command routing (Stage 48M)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    src = (PROJECT_ROOT / 'backend/telegram/telegram_command_normalize.py').read_text(encoding='utf-8')
    if 'resolve_natural_command' not in src:
        print('TELEGRAM_NATURAL_STOCK_COMMANDS_FAIL: missing resolve_natural_command', file=sys.stderr)
        return 1
    if os.system(f'{sys.executable} scripts/test_telegram_natural_stock_commands.py') != 0:
        return 1
    print('TELEGRAM_NATURAL_STOCK_COMMANDS_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
