#!/usr/bin/env python3
"""
Start Telegram Analysis Bot listener + optional brief scheduler (Stage 45TG3).

Usage:
  python scripts/run_telegram_analysis_bot.py

Environment:
  TELEGRAM_BRIEF_SCHEDULER=1  — enable IST scheduled briefs
  DISABLE_TELEGRAM_LISTENER=0 — required for polling
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if str(Path.cwd().resolve()) != str(PROJECT_ROOT.resolve()):
    os.chdir(PROJECT_ROOT)


def _env_truthy(name: str) -> bool:
    return os.environ.get(name, '').strip().lower() in ('1', 'true', 'yes', 'on')


def main() -> int:
    from backend.telegram.lazy_command_runner import STAGE_MARKER
    from backend.telegram.response_format import TRADE_EXECUTION_PERMANENTLY_DISABLED
    from backend.telegram.telegram_analysis_bot import listen_forever
    from backend.utils.telegram_guard import is_telegram_listener_enabled

    print('[TG_ANALYSIS_RUNNER] starting Telegram Analysis Bot')
    print(f'[TG_ANALYSIS_RUNNER] stage_marker={STAGE_MARKER}')
    print(f'[TG_ANALYSIS_RUNNER] trade_execution_disabled={TRADE_EXECUTION_PERMANENTLY_DISABLED}')

    if not is_telegram_listener_enabled():
        print('[TG_ANALYSIS_RUNNER] listener disabled — set DISABLE_TELEGRAM_LISTENER=0 to enable')
        return 1

    token_set = bool(os.environ.get('TELEGRAM_BOT_TOKEN', '').strip())
    chat_set = bool(os.environ.get('TELEGRAM_CHAT_ID', '').strip())
    print(f'[TG_ANALYSIS_RUNNER] credentials_present token={token_set} chat={chat_set}')

    if _env_truthy('TELEGRAM_BRIEF_SCHEDULER'):
        from backend.telegram.telegram_brief_scheduler import start_brief_scheduler

        start_brief_scheduler()
        print('[TG_ANALYSIS_RUNNER] brief scheduler enabled (IST)')

    listen_forever()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
