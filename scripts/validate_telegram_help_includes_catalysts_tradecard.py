#!/usr/bin/env python3
"""Validate Stage 50O — help includes catalyst/tradecard commands."""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)


def _fail(msg: str) -> int:
    print(f'TELEGRAM_HELP_INCLUDES_CATALYSTS_TRADECARD_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    help_src = (PROJECT_ROOT / 'backend/telegram/telegram_analysis_bot.py').read_text(encoding='utf-8')
    for needle in (
        '<b>Catalyst Radar:</b>',
        '/catalysts — stock-specific catalyst radar',
        '<b>Trade Card:</b>',
        '/tradecard — one-stock paper trade card',
        "cmd == 'catalysts'",
        "cmd == 'tradecard'",
    ):
        if needle not in help_src:
            return _fail(f'telegram_analysis_bot missing {needle!r}')

    proc = os.system(f'{sys.executable} scripts/test_telegram_help_includes_catalysts_tradecard.py')
    if proc != 0:
        return _fail('test_telegram_help_includes_catalysts_tradecard.py failed')
    print('TELEGRAM_HELP_INCLUDES_CATALYSTS_TRADECARD_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
