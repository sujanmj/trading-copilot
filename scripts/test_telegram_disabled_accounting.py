#!/usr/bin/env python3
"""Verify disabled Telegram sends are counted as skipped, not sent."""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Force local disabled flags before config/guard imports.
os.environ['DISABLE_TELEGRAM'] = '1'
os.environ['DISABLE_TELEGRAM_SENDS'] = '1'
os.environ['DISABLE_TELEGRAM_LISTENER'] = '1'
os.environ['LOCAL_ONLY'] = '1'

if str(Path.cwd().resolve()) != str(PROJECT_ROOT.resolve()):
    os.chdir(PROJECT_ROOT)

sys.path.insert(0, str(PROJECT_ROOT))


def main() -> int:
    from backend.utils.telegram_bot import send_message_result
    from backend.utils.telegram_guard import TELEGRAM_DISABLED_SEND_RESULT

    result = send_message_result('local-mode accounting probe')

    expected = dict(TELEGRAM_DISABLED_SEND_RESULT)
    for key, value in expected.items():
        if result.get(key) != value:
            print(
                f'TELEGRAM_DISABLED_ACCOUNTING_FAIL: {key}={result.get(key)!r} expected {value!r}',
                file=sys.stderr,
            )
            return 1

    if result.get('sent'):
        print('TELEGRAM_DISABLED_ACCOUNTING_FAIL: sent=True when Telegram disabled', file=sys.stderr)
        return 1

    print('TELEGRAM_DISABLED_ACCOUNTING_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
