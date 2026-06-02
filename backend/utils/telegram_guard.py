"""
Central Telegram activity guard — blocks sends/polls when disabled.

Used by listener, brain pusher, alert routing, and legacy bot helpers.
Railway/production remains unchanged unless DISABLE_* flags are set.
Local laptop dry-runs sends unless ALLOW_LOCAL_TELEGRAM_SENDS=1 (Stage 46C).
"""

from __future__ import annotations

from backend.utils.config import DISABLE_TELEGRAM, DISABLE_TELEGRAM_LISTENER, DISABLE_TELEGRAM_SENDS

TELEGRAM_DISABLED_SEND_RESULT = {
    'ok': False,
    'sent': False,
    'skipped': True,
    'reason': 'telegram_disabled',
}

TELEGRAM_DRY_RUN_SEND_RESULT = {
    'ok': True,
    'sent': False,
    'skipped': False,
    'dry_run': True,
    'reason': 'local_telegram_sends_dry_run',
}


def _local_send_dry_run_active() -> bool:
    try:
        from backend.config.local_safe_mode import local_telegram_send_dry_run

        return local_telegram_send_dry_run()
    except Exception:
        return False


def is_telegram_send_enabled() -> bool:
    """True when outbound Telegram API calls are allowed."""
    return not (DISABLE_TELEGRAM or DISABLE_TELEGRAM_SENDS)


def is_telegram_listener_enabled() -> bool:
    """True when Telegram polling/listener may run."""
    return not (DISABLE_TELEGRAM or DISABLE_TELEGRAM_LISTENER)


def telegram_send_skipped(context: str = '') -> dict:
    """Log and return a structured skipped result for disabled outbound sends."""
    suffix = f' ({context})' if context else ''
    print(f'[TELEGRAM DISABLED] send skipped{suffix}', flush=True)
    return dict(TELEGRAM_DISABLED_SEND_RESULT)


def telegram_send_dry_run(context: str = '', *, text: str = '') -> dict:
    """Log local dry-run and return structured result (no Telegram API call)."""
    from backend.config.local_safe_mode import LOCAL_TELEGRAM_SENDS_DRY_RUN_MSG

    suffix = f' ({context})' if context else ''
    print(f'{LOCAL_TELEGRAM_SENDS_DRY_RUN_MSG}{suffix}', flush=True)
    result = dict(TELEGRAM_DRY_RUN_SEND_RESULT)
    if text:
        result['text'] = text
    return result


def guard_telegram_send(context: str = '') -> bool:
    """
    Return True to proceed with a send.
    When disabled or local dry-run, logs and returns False.
    """
    if DISABLE_TELEGRAM or DISABLE_TELEGRAM_SENDS:
        suffix = f' ({context})' if context else ''
        print(f'[TELEGRAM DISABLED] send skipped{suffix}', flush=True)
        return False
    if _local_send_dry_run_active():
        telegram_send_dry_run(context)
        return False
    return True


def guard_telegram_poll(context: str = '') -> bool:
    """Return True to proceed with getUpdates / listener polling."""
    if is_telegram_listener_enabled():
        return True
    suffix = f' ({context})' if context else ''
    print(f'[TELEGRAM DISABLED] poll skipped{suffix}', flush=True)
    return False
