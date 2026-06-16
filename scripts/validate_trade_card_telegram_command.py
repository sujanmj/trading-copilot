#!/usr/bin/env python3
"""Validate Stage 50Q /tradecard command wiring."""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)


def _fail(msg: str) -> int:
    print(f'TRADE_CARD_TELEGRAM_COMMAND_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    for path in (
        'backend/telegram/lazy_command_runner.py',
        'backend/telegram/response_format.py',
        'backend/telegram/telegram_analysis_bot.py',
    ):
        src = (PROJECT_ROOT / path).read_text(encoding='utf-8')
        if 'tradecard' not in src.lower():
            return _fail(f'{path} missing tradecard wiring')
    proc = os.system(f'{sys.executable} scripts/test_trade_card_telegram_command.py')
    if proc != 0:
        return _fail('test_trade_card_telegram_command.py failed')
    print('TRADE_CARD_TELEGRAM_COMMAND_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
