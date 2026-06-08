#!/usr/bin/env python3
"""Validate get_top_broker_display_candidates backward compatibility (48L hotfix)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)


def _fail(msg: str) -> int:
    print(f'BROKER_DISPLAY_CANDIDATES_COMPAT_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    broker_path = PROJECT_ROOT / 'backend/analytics/broker_prediction_intelligence.py'
    lazy_path = PROJECT_ROOT / 'backend/telegram/lazy_command_runner.py'
    broker_src = broker_path.read_text(encoding='utf-8')
    lazy_src = lazy_path.read_text(encoding='utf-8')

    for symbol, src in (
        ('def get_top_broker_display_candidates', broker_src),
        ('_display_candidates_from_intel_cache', broker_src),
        ('get_broker_intel_overview', broker_src),
        ('get_top_broker_display_candidates', lazy_src),
    ):
        if symbol not in src:
            return _fail(f'missing symbol: {symbol}')

    if os.system(f'{sys.executable} scripts/test_broker_display_candidates_compat.py') != 0:
        return _fail('test_broker_display_candidates_compat.py failed')

    if os.system(f'{sys.executable} scripts/validate_telegram_data_accuracy.py') != 0:
        return _fail('validate_telegram_data_accuracy.py failed')

    if os.system(f'{sys.executable} scripts/validate_broker_telegram_commands.py') != 0:
        return _fail('validate_broker_telegram_commands.py failed')

    print('BROKER_DISPLAY_CANDIDATES_COMPAT_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
