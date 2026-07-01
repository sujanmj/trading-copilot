"""
Local safe mode — laptop defaults when Railway is the live control plane (Stage 46D).

When not on Railway, Telegram listener/sends and trade execution are disabled by default.
Explicit opt-in: ALLOW_LOCAL_TELEGRAM=1, ALLOW_LOCAL_TELEGRAM_SENDS=1.

Railway defaults DISABLE_LEGACY_TELEGRAM_LISTENER=1 so api_server never starts
telegram_listener.py (ML Elite); use run_railway_telegram_worker + telegram_analysis_bot.
"""

from __future__ import annotations

import os

STAGE_MARKER = 'LOCAL_STAGE_46C_SAFE_RAILWAY_CONTROL'
RAILWAY_TELEGRAM_HANDLER_STAGE = 'RAILWAY_STAGE_46E_MONOLITH_TELEGRAM'
ASTRAEDGE_TELEGRAM_BUILD = 'AstraEdge 51B'
ASTRAEDGE_BUILD_STAGE = '51B'


def get_astraedge_build_stage() -> str:
    """Short deployment stage id shared by /status, build-info, and smoke checks."""
    return ASTRAEDGE_BUILD_STAGE

LOCAL_SAFE_DEFAULTS: dict[str, str] = {
    'DISABLE_TELEGRAM': '1',
    'DISABLE_TELEGRAM_SENDS': '1',
    'DISABLE_TELEGRAM_LISTENER': '1',
    'DISABLE_LEGACY_TELEGRAM_LISTENER': '1',
    'TELEGRAM_COMMANDS_ENABLED': '0',
    'TELEGRAM_BRIEF_SCHEDULER': '0',
    'TELEGRAM_TRADE_COMMANDS_ENABLED': '0',
    'DISABLE_TRADE_EXECUTION': '1',
}

RAILWAY_TELEGRAM_DEFAULTS: dict[str, str] = {
    'DISABLE_LEGACY_TELEGRAM_LISTENER': '1',
}

LOCAL_TELEGRAM_DISABLED_MSG = 'LOCAL_TELEGRAM_DISABLED_RAILWAY_IS_LIVE'
LOCAL_TELEGRAM_SENDS_DRY_RUN_MSG = 'LOCAL_TELEGRAM_SENDS_DRY_RUN'


def _env_truthy(name: str) -> bool:
    return os.environ.get(name, '').strip().lower() in ('1', 'true', 'yes', 'on')


def is_railway_mode() -> bool:
    """True when running as Railway deployment (APP_MODE=railway or RAILWAY_ENVIRONMENT set)."""
    if os.environ.get('APP_MODE', '').strip().lower() == 'railway':
        return True
    if os.environ.get('RAILWAY_ENVIRONMENT', '').strip():
        return True
    return False


def is_local_safe_mode() -> bool:
    return not is_railway_mode()


def apply_local_safe_mode_defaults() -> bool:
    """
    Apply local-safe env defaults when not on Railway.

    Uses setdefault so explicit env vars (including Railway) are never overridden.
    Returns True when defaults were applied (local mode).
    """
    if is_railway_mode():
        return False
    for key, value in LOCAL_SAFE_DEFAULTS.items():
        os.environ.setdefault(key, value)
    return True


def apply_railway_telegram_defaults() -> bool:
    """
    Apply Railway Telegram handler defaults (legacy listener off by default).

    Uses setdefault so explicit env vars are never overridden.
    Returns True when running in Railway mode.
    """
    if not is_railway_mode():
        return False
    for key, value in RAILWAY_TELEGRAM_DEFAULTS.items():
        os.environ.setdefault(key, value)
    return True


def is_legacy_telegram_listener_disabled() -> bool:
    """True when telegram_listener.py (ML Elite) must not start."""
    return _env_truthy('DISABLE_LEGACY_TELEGRAM_LISTENER')


def is_railway_telegram_start_dry_run() -> bool:
    """True when Railway Telegram start tests must not poll/send (Stage 46E)."""
    return _env_truthy('RAILWAY_TELEGRAM_START_DRY_RUN')


def allow_local_telegram() -> bool:
    """True when local Telegram listener/runner may start."""
    if is_railway_mode():
        return True
    return _env_truthy('ALLOW_LOCAL_TELEGRAM')


def allow_local_telegram_sends() -> bool:
    """True when local outbound Telegram API calls may proceed (not dry-run)."""
    if is_railway_mode():
        return True
    return _env_truthy('ALLOW_LOCAL_TELEGRAM_SENDS')


def local_telegram_runner_blocked() -> bool:
    """True when run_telegram_analysis_bot must refuse to start."""
    return is_local_safe_mode() and not allow_local_telegram()


def local_telegram_send_dry_run() -> bool:
    """True when outbound sends should dry-run (local, sends not explicitly allowed)."""
    if is_railway_mode():
        return False
    return not allow_local_telegram_sends()
