#!/usr/bin/env python3
"""Validate premarket alerts pack (Stage 46H)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)


def _fail(msg: str) -> int:
    print(f'PREMARKET_ALERTS_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    root = PROJECT_ROOT
    required = [
        root / 'backend/analytics/premarket_conviction.py',
        root / 'backend/telegram/premarket_scheduler.py',
    ]
    for path in required:
        if not path.is_file():
            return _fail(f'missing {path.relative_to(root)}')

    bot_src = (root / 'backend/telegram/telegram_analysis_bot.py').read_text(encoding='utf-8')
    for needle in ('cmd == \'premarket\'', '_handle_premarket', 'start_premarket_scheduler'):
        if needle not in bot_src:
            return _fail(f'telegram bot missing {needle}')

    sched_src = (root / 'backend/telegram/premarket_scheduler.py').read_text(encoding='utf-8')
    for t in ('07:45', '08:00', '08:15', '08:30', '08:45', '09:00', '09:20', '09:25', '09:31'):
        if t not in sched_src:
            return _fail(f'scheduler missing time {t}')
    if '09:10' in sched_src and 'preopen_watch' in sched_src:
        return _fail('scheduler must not include 09:10 preopen_watch')

    proc = os.system(f'{sys.executable} scripts/test_premarket_alerts.py')
    if proc != 0:
        return _fail('test_premarket_alerts.py failed')

    print('PREMARKET_ALERTS_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
