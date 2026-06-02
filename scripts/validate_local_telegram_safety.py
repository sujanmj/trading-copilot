#!/usr/bin/env python3
"""
Validate local Telegram send-only safety gates (Stage 42A).

Usage:
  python scripts/validate_local_telegram_safety.py
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

NOTIFIER_PATH = PROJECT_ROOT / 'backend' / 'notifications' / 'local_telegram_notifier.py'
RUN_LOCAL_PATH = PROJECT_ROOT / 'run_local.py'


def _fail(msg: str) -> int:
    print(f'LOCAL_TELEGRAM_SAFETY_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    os.environ.setdefault('LOCAL_DEV_MODE', '1')
    os.environ.setdefault('LOCAL_ONLY', '1')
    os.environ.setdefault('DISABLE_TELEGRAM', '1')
    os.environ.setdefault('DISABLE_TELEGRAM_LISTENER', '1')
    os.environ.setdefault('DISABLE_TELEGRAM_SENDS', '1')

    if not NOTIFIER_PATH.is_file():
        return _fail('local_telegram_notifier.py missing')

    src = NOTIFIER_PATH.read_text(encoding='utf-8')
    required_fragments = (
        'LOCAL ONLY',
        'Shadow analysis only',
        'Not trade execution',
        'ENABLE_LOCAL_TELEGRAM_NOTIFICATIONS',
        'DISABLE_TELEGRAM_SENDS',
        'DISABLE_TELEGRAM_LISTENER',
        'blocked_notification_type',
        'telegram_listener_must_be_disabled',
        'local_mode_required',
    )
    for fragment in required_fragments:
        if fragment not in src:
            return _fail(f'missing safety fragment: {fragment}')

    if 'TELEGRAM_BOT_TOKEN' in src and 'print' in src:
        # Ensure we do not print token values
        if re_search_prints_token(src):
            return _fail('notifier may print Telegram secrets')

    run_local_src = RUN_LOCAL_PATH.read_text(encoding='utf-8') if RUN_LOCAL_PATH.is_file() else ''
    if 'DISABLE_TELEGRAM_LISTENER' not in run_local_src:
        return _fail('run_local.py missing DISABLE_TELEGRAM_LISTENER default')

    from backend.notifications import local_telegram_notifier as mod
    from backend.utils import telegram_guard as tg

    if tg.is_telegram_listener_enabled():
        return _fail('telegram_guard listener enabled under default local env')

    if tg.is_telegram_send_enabled():
        return _fail('telegram_guard global send enabled under default local env')

    status = mod.telegram_notifications_enabled()
    if status.get('enabled'):
        return _fail('local notifier enabled while DISABLE_TELEGRAM_SENDS=1 default')

    for blocked_type in ('trade_execution', 'order_placement'):
        refused = mod.send_local_telegram_message('x', notification_type=blocked_type)
        if refused.get('reason') != 'blocked_notification_type':
            return _fail(f'{blocked_type} not blocked: {refused.get("reason")!r}')

    # Dry-run style check: no token/chat echoed
    blob = str(status)
    token = os.environ.get('TELEGRAM_BOT_TOKEN', '').strip()
    chat_id = os.environ.get('TELEGRAM_CHAT_ID', '').strip()
    if token and token in blob:
        return _fail('status dict leaked bot token')
    if chat_id and chat_id in blob:
        return _fail('status dict leaked chat id')

    print('LOCAL_TELEGRAM_SAFETY_OK')
    return 0


def re_search_prints_token(src: str) -> bool:
    import re

    risky = re.findall(r'print\s*\([^)]*TELEGRAM_BOT_TOKEN[^)]*\)', src, flags=re.IGNORECASE)
    risky += re.findall(r'print\s*\([^)]*TELEGRAM_CHAT_ID[^)]*\)', src, flags=re.IGNORECASE)
    return bool(risky)


if __name__ == '__main__':
    raise SystemExit(main())
