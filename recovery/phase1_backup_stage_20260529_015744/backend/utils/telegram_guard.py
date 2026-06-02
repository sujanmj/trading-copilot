"""
Central Telegram activity guard — blocks sends/polls when disabled.

Used by listener, brain pusher, alert routing, and legacy bot helpers.
Railway/production remains unchanged unless DISABLE_* flags are set.
"""

from __future__ import annotations

from backend.utils.config import DISABLE_TELEGRAM, DISABLE_TELEGRAM_LISTENER, DISABLE_TELEGRAM_SENDS


def is_telegram_send_enabled() -> bool:
    """True when outbound Telegram API calls are allowed."""
    return not (DISABLE_TELEGRAM or DISABLE_TELEGRAM_SENDS)


def is_telegram_listener_enabled() -> bool:
    """True when Telegram polling/listener may run."""
    return not (DISABLE_TELEGRAM or DISABLE_TELEGRAM_LISTENER)


def guard_telegram_send(context: str = '') -> bool:
    """
    Return True to proceed with a send.
    When disabled, logs once-per-call and returns False (caller should no-op as success).
    """
    if is_telegram_send_enabled():
        return True
    suffix = f' ({context})' if context else ''
    print(f'[TELEGRAM DISABLED] send skipped{suffix}', flush=True)
    return False


def guard_telegram_poll(context: str = '') -> bool:
    """Return True to proceed with getUpdates / listener polling."""
    if is_telegram_listener_enabled():
        return True
    suffix = f' ({context})' if context else ''
    print(f'[TELEGRAM DISABLED] poll skipped{suffix}', flush=True)
    return False
