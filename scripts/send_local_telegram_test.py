#!/usr/bin/env python3
"""
Send one local-only Telegram test message (Stage 42A).

Usage:
  python scripts/send_local_telegram_test.py --dry-run --message "Local Telegram dry run"
  python scripts/send_local_telegram_test.py --message "Trading Copilot local Telegram test"
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if str(Path.cwd().resolve()) != str(PROJECT_ROOT.resolve()):
    os.chdir(PROJECT_ROOT)


def _apply_send_env() -> None:
    os.environ.setdefault('LOCAL_DEV_MODE', '1')
    os.environ.setdefault('LOCAL_ONLY', '1')
    os.environ.setdefault('DISABLE_TELEGRAM', '1')
    os.environ.setdefault('DISABLE_TELEGRAM_LISTENER', '1')
    os.environ['DISABLE_TELEGRAM_SENDS'] = '0'
    os.environ['ENABLE_LOCAL_TELEGRAM_NOTIFICATIONS'] = '1'


def main() -> int:
    parser = argparse.ArgumentParser(description='Local Telegram send-only test CLI')
    parser.add_argument('--dry-run', action='store_true', help='Format message only; no HTTP send')
    parser.add_argument('--message', default='Trading Copilot local Telegram test')
    args = parser.parse_args()

    _apply_send_env()

    from backend.notifications.local_telegram_notifier import (
        _apply_safety_footer,
        send_local_telegram_message,
        telegram_notifications_enabled,
    )

    message = _apply_safety_footer(args.message)
    status = telegram_notifications_enabled()

    if args.dry_run:
        print(message)
        print(f'[LOCAL_TG] enabled={status.get("enabled")} credentials={status.get("credentials_configured")}')
        if status.get('reasons'):
            print(f'[LOCAL_TG] gates={",".join(status.get("reasons") or [])}')
        print('LOCAL_TELEGRAM_TEST_DRY_RUN_OK')
        return 0

    result = send_local_telegram_message(message, notification_type='test')
    if result.get('sent'):
        print('LOCAL_TELEGRAM_TEST_SENT_OK')
        return 0

    reason = result.get('reason') or 'unknown'
    print(f'LOCAL_TELEGRAM_TEST_FAIL: {reason}', file=sys.stderr)
    if reason == 'missing_credentials':
        print('LOCAL_TELEGRAM_TEST_SKIP: configure TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in keys.env', file=sys.stderr)
        return 2
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
