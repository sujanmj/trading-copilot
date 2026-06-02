#!/usr/bin/env python3
"""
Railway Telegram analysis bot worker (Stage 46A).

Usage:
  python scripts/run_railway_telegram_worker.py

Requires safe command-mode env. Never prints token or chat id values.
"""

from __future__ import annotations

import os
import sys

_RAILWAY_WORKER_DEFAULTS = {
    'LOCAL_DEV_MODE': '0',
    'LOCAL_ONLY': '0',
    'APP_MODE': 'railway',
    'TZ': 'Asia/Kolkata',
    'PYTHONIOENCODING': 'utf-8',
    'PYTHONUTF8': '1',
    'DISABLE_TELEGRAM': '0',
    'DISABLE_TELEGRAM_LISTENER': '0',
    'DISABLE_TELEGRAM_SENDS': '0',
    'TELEGRAM_COMMANDS_ENABLED': '1',
    'TELEGRAM_TRADE_COMMANDS_ENABLED': '0',
    'DISABLE_TRADE_EXECUTION': '1',
}
for _key, _val in _RAILWAY_WORKER_DEFAULTS.items():
    os.environ.setdefault(_key, _val)

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if str(Path.cwd().resolve()) != str(PROJECT_ROOT.resolve()):
    os.chdir(PROJECT_ROOT)

from backend.utils.bootstrap import setup_project_path

setup_project_path()


def _env_truthy(name: str) -> bool:
    return os.environ.get(name, '').strip().lower() in ('1', 'true', 'yes', 'on')


def _fail(message: str) -> int:
    print(f'[RAILWAY_TG_WORKER] fail={message}', flush=True)
    return 1


def _validate_safety_env() -> int | None:
    if not _env_truthy('TELEGRAM_COMMANDS_ENABLED'):
        return _fail('TELEGRAM_COMMANDS_ENABLED must be 1')
    if _env_truthy('TELEGRAM_TRADE_COMMANDS_ENABLED'):
        return _fail('TELEGRAM_TRADE_COMMANDS_ENABLED must be 0')
    if not _env_truthy('DISABLE_TRADE_EXECUTION'):
        return _fail('DISABLE_TRADE_EXECUTION must be 1')
    return None


def main() -> int:
    safety_error = _validate_safety_env()
    if safety_error is not None:
        return safety_error

    from backend.telegram.lazy_command_runner import STAGE_MARKER
    from backend.telegram.response_format import TRADE_EXECUTION_PERMANENTLY_DISABLED
    from backend.telegram.telegram_analysis_bot import listen_forever
    from backend.utils.telegram_guard import is_telegram_listener_enabled

    token_set = bool(os.environ.get('TELEGRAM_BOT_TOKEN', '').strip())
    chat_set = bool(os.environ.get('TELEGRAM_CHAT_ID', '').strip())

    print('[RAILWAY_TG_WORKER] starting Telegram analysis bot', flush=True)
    print(f'[RAILWAY_TG_WORKER] stage_marker={STAGE_MARKER}', flush=True)
    print(f'[RAILWAY_TG_WORKER] trade_execution_disabled={TRADE_EXECUTION_PERMANENTLY_DISABLED}', flush=True)
    print(f'[RAILWAY_TG_WORKER] credentials_present token={token_set} chat={chat_set}', flush=True)

    if not is_telegram_listener_enabled():
        return _fail('telegram listener disabled by guard flags')

    if not token_set or not chat_set:
        return _fail('TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID required')

    if _env_truthy('TELEGRAM_BRIEF_SCHEDULER'):
        from backend.telegram.telegram_brief_scheduler import start_brief_scheduler

        start_brief_scheduler()
        print('[RAILWAY_TG_WORKER] brief scheduler enabled (IST)', flush=True)

    listen_forever()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
