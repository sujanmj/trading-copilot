#!/usr/bin/env python3
"""Unit tests for local Telegram send-only notifier (mocked HTTP)."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if str(Path.cwd().resolve()) != str(PROJECT_ROOT.resolve()):
    os.chdir(PROJECT_ROOT)


def _reset_config_modules() -> None:
    for name in list(sys.modules):
        if name == 'backend.utils.config' or name.startswith('backend.notifications'):
            sys.modules.pop(name, None)


def _set_env(**kwargs: str) -> None:
    for key, val in kwargs.items():
        os.environ[key] = val


def _local_send_env() -> None:
    _set_env(
        LOCAL_DEV_MODE='1',
        LOCAL_ONLY='1',
        DISABLE_TELEGRAM='1',
        DISABLE_TELEGRAM_LISTENER='1',
        DISABLE_TELEGRAM_SENDS='0',
        ENABLE_LOCAL_TELEGRAM_NOTIFICATIONS='1',
        TELEGRAM_BOT_TOKEN='test-token',
        TELEGRAM_CHAT_ID='12345',
    )


def main() -> int:
    # Default local-disabled posture (matches run_local.py)
    _set_env(
        LOCAL_DEV_MODE='1',
        LOCAL_ONLY='1',
        DISABLE_TELEGRAM='1',
        DISABLE_TELEGRAM_LISTENER='1',
        DISABLE_TELEGRAM_SENDS='1',
        ENABLE_LOCAL_TELEGRAM_NOTIFICATIONS='0',
    )
    _reset_config_modules()

    from backend.notifications import local_telegram_notifier as mod

    disabled = mod.telegram_notifications_enabled()
    if disabled.get('enabled'):
        print('LOCAL_TELEGRAM_NOTIFIER_TEST_FAIL: enabled by default', file=sys.stderr)
        return 1

    blocked = mod.send_local_telegram_message('probe', notification_type='test')
    if blocked.get('sent') or blocked.get('reason') not in (
        'telegram_sends_disabled',
        'local_telegram_notifications_disabled',
    ):
        if blocked.get('reason') not in ('telegram_sends_disabled', 'local_telegram_notifications_disabled'):
            print(
                f'LOCAL_TELEGRAM_NOTIFIER_TEST_FAIL: default send reason={blocked.get("reason")!r}',
                file=sys.stderr,
            )
            return 1

    # Listener enabled must block
    _local_send_env()
    os.environ['DISABLE_TELEGRAM_LISTENER'] = '0'
    _reset_config_modules()
    from backend.notifications import local_telegram_notifier as mod_listener

    listener_block = mod_listener.send_local_telegram_message('probe', notification_type='test')
    if listener_block.get('reason') != 'telegram_listener_must_be_disabled':
        print(
            f'LOCAL_TELEGRAM_NOTIFIER_TEST_FAIL: listener gate reason={listener_block.get("reason")!r}',
            file=sys.stderr,
        )
        return 1

    # Local mode off must block
    _set_env(LOCAL_DEV_MODE='0', LOCAL_ONLY='0')
    _reset_config_modules()
    from backend.notifications import local_telegram_notifier as mod_no_local

    no_local = mod_no_local.send_local_telegram_message('probe', notification_type='test')
    if no_local.get('reason') != 'local_mode_required':
        print(
            f'LOCAL_TELEGRAM_NOTIFIER_TEST_FAIL: local mode reason={no_local.get("reason")!r}',
            file=sys.stderr,
        )
        return 1

    # Trade/order types blocked
    _local_send_env()
    _reset_config_modules()
    from backend.notifications import local_telegram_notifier as mod_trade

    for bad_type in ('trade_execution', 'order_placement', 'auto_buy', 'scanner_alert'):
        refused = mod_trade.send_local_telegram_message('probe', notification_type=bad_type)
        if refused.get('reason') != 'blocked_notification_type':
            print(
                f'LOCAL_TELEGRAM_NOTIFIER_TEST_FAIL: {bad_type} reason={refused.get("reason")!r}',
                file=sys.stderr,
            )
            return 1

    # Safe test allowed with mock HTTP
    _local_send_env()
    _reset_config_modules()
    from backend.notifications import local_telegram_notifier as mod_ok

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {'ok': True}

    with patch('requests.post', return_value=mock_resp) as mock_post:
        sent = mod_ok.send_local_telegram_message('Local test body', notification_type='test')
        if not sent.get('sent'):
            print(
                f'LOCAL_TELEGRAM_NOTIFIER_TEST_FAIL: mock send failed reason={sent.get("reason")!r}',
                file=sys.stderr,
            )
            return 1
        if mock_post.call_count != 1:
            print('LOCAL_TELEGRAM_NOTIFIER_TEST_FAIL: expected one HTTP call', file=sys.stderr)
            return 1
        payload = mock_post.call_args.kwargs.get('json') or mock_post.call_args[1].get('json')
        text = str((payload or {}).get('text') or '')
        for line in mod_ok.SAFETY_LINES:
            if line not in text:
                print(f'LOCAL_TELEGRAM_NOTIFIER_TEST_FAIL: missing safety line {line!r}', file=sys.stderr)
                return 1

    print('LOCAL_TELEGRAM_NOTIFIER_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
