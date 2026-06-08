#!/usr/bin/env python3
"""Validate scheduled stale macro Telegram suppression (Stage 48G)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)


def _fail(msg: str) -> int:
    print(f'TELEGRAM_STALE_MACRO_SUPPRESSION_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    src = (PROJECT_ROOT / 'backend/orchestration/telegram_alert_engine.py').read_text(encoding='utf-8')
    for needle in (
        'def try_emergency_macro(scheduled: bool = True)',
        'TELEGRAM_MACRO_STALE_SUPPRESSED',
        'scheduled: bool = True',
    ):
        if needle not in src:
            return _fail(f'telegram_alert_engine missing {needle!r}')

    if os.system(f'{sys.executable} scripts/test_telegram_stale_macro_suppression.py') != 0:
        return _fail('test_telegram_stale_macro_suppression.py failed')

    print('TELEGRAM_STALE_MACRO_SUPPRESSION_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
