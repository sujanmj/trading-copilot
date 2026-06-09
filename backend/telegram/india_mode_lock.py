"""
India-centric Telegram market mode lock — Stage 48K / 48S.

Telegram must not show USA_MODE unless TELEGRAM_ALLOW_USA_MODE is explicitly set.
Market phase labels match /status (INDIA_AFTER_HOURS, INDIA_MARKET_HOURS, etc.).
"""

from __future__ import annotations

import os
from typing import Any

from backend.analytics.market_calendar_router import (
    get_india_telegram_mode,
    is_weekend_holiday_research_telegram_mode,
)

_INDIA_MODE_CODES = frozenset({
    'INDIA_MODE',
    'INDIA_MARKET_HOURS',
    'INDIA_PREMARKET_MODE',
    'INDIA_PREOPEN_MODE',
    'INDIA_POSTMARKET_MODE',
    'INDIA_AFTER_HOURS_MODE',
    'INDIA_AFTER_HOURS',
    'RESEARCH_MODE',
})

_CODE_TO_PHASE = {
    'INDIA_AFTER_HOURS_MODE': 'INDIA_AFTER_HOURS',
    'INDIA_MARKET_HOURS_MODE': 'INDIA_MARKET_HOURS',
    'INDIA_MARKET_HOURS': 'INDIA_MARKET_HOURS',
    'INDIA_PREMARKET_MODE': 'INDIA_PREMARKET_MODE',
    'INDIA_PREOPEN_MODE': 'INDIA_PREOPEN_MODE',
    'INDIA_POSTMARKET_MODE': 'INDIA_POSTMARKET_MODE',
    'INDIA_MODE': 'INDIA_MARKET_HOURS',
    'RESEARCH_MODE': 'RESEARCH_MODE',
}


def explicit_usa_mode_configured() -> bool:
    token = os.environ.get('TELEGRAM_ALLOW_USA_MODE', '').strip().lower()
    return token in ('1', 'true', 'yes', 'usa_mode')


def _normalize_mode_token(value: Any) -> str:
    return str(value or '').strip().upper().replace(' ', '_')


def _phase_from_token(token: str) -> str:
    if not token:
        return ''
    if token in _CODE_TO_PHASE:
        return _CODE_TO_PHASE[token]
    if token.endswith('_MODE') and token[:-5] in _CODE_TO_PHASE:
        return _CODE_TO_PHASE[token[:-5]]
    if token.startswith('INDIA_'):
        return token
    if token == 'RESEARCH_MODE' or 'RESEARCH' in token:
        return 'RESEARCH_MODE'
    return token


def resolve_telegram_market_phase(
    *,
    payload_mode: str | None = None,
    router_mode: str | None = None,
    pack_mode: str | None = None,
    summary_mode: str | None = None,
    active_mode: str | None = None,
) -> str:
    """Canonical market phase for all Telegram surfaces — matches /status."""
    candidates = (
        payload_mode,
        router_mode,
        pack_mode,
        summary_mode,
        active_mode,
    )
    if explicit_usa_mode_configured():
        for raw in candidates:
            if _normalize_mode_token(raw) == 'USA_MODE':
                return 'USA_MODE'

    try:
        india = get_india_telegram_mode()
    except Exception:
        india = {}

    if is_weekend_holiday_research_telegram_mode(india):
        return 'RESEARCH_MODE'

    label = _phase_from_token(_normalize_mode_token(india.get('market_mode')))
    if label:
        return label

    code = _phase_from_token(_normalize_mode_token(india.get('mode_code')))
    if code:
        return code

    for raw in candidates:
        token = _normalize_mode_token(raw)
        if token.startswith('INDIA_') or token == 'RESEARCH_MODE':
            return _phase_from_token(token)

    return 'RESEARCH_MODE'


def resolve_telegram_market_mode(
    *,
    payload_mode: str | None = None,
    router_mode: str | None = None,
    pack_mode: str | None = None,
    summary_mode: str | None = None,
    active_mode: str | None = None,
) -> str:
    """Backward-compatible alias — returns canonical market phase."""
    return resolve_telegram_market_phase(
        payload_mode=payload_mode,
        router_mode=router_mode,
        pack_mode=pack_mode,
        summary_mode=summary_mode,
        active_mode=active_mode,
    )


def is_after_hours_phase(phase: str | None = None) -> bool:
    return (phase or resolve_telegram_market_phase()) == 'INDIA_AFTER_HOURS'


def is_live_market_hours_phase(phase: str | None = None) -> bool:
    return (phase or resolve_telegram_market_phase()) == 'INDIA_MARKET_HOURS'


def is_premarket_phase(phase: str | None = None) -> bool:
    return (phase or resolve_telegram_market_phase()) in {
        'INDIA_PREMARKET_MODE',
        'INDIA_PREOPEN_MODE',
    }


def lock_mode_in_text(text: str, *, resolved_mode: str | None = None) -> str:
    """Replace leaked USA_MODE tokens in formatted Telegram text."""
    mode = resolved_mode or resolve_telegram_market_phase()
    if explicit_usa_mode_configured() and mode == 'USA_MODE':
        return text
    return text.replace('USA_MODE', mode).replace('usa_mode', mode.lower())
