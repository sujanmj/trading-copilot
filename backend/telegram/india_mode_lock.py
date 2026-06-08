"""
India-centric Telegram market mode lock — Stage 48K.

Telegram must not show USA_MODE unless TELEGRAM_ALLOW_USA_MODE is explicitly set.
"""

from __future__ import annotations

import os
from typing import Any

from backend.analytics.market_calendar_router import (
    MODE_RESEARCH,
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
})


def explicit_usa_mode_configured() -> bool:
    token = os.environ.get('TELEGRAM_ALLOW_USA_MODE', '').strip().lower()
    return token in ('1', 'true', 'yes', 'usa_mode')


def _normalize_mode_token(value: Any) -> str:
    return str(value or '').strip().upper().replace(' ', '_')


def resolve_telegram_market_mode(
    *,
    payload_mode: str | None = None,
    router_mode: str | None = None,
    pack_mode: str | None = None,
    summary_mode: str | None = None,
    active_mode: str | None = None,
) -> str:
    """
    India-centric display mode for Telegram surfaces.

    Priority:
    1. Explicit TELEGRAM_ALLOW_USA_MODE + USA_MODE in sources → USA_MODE
    2. India calendar (open session) → INDIA_MODE
    3. Weekend/holiday/closed → RESEARCH_MODE
    Never infer USA_MODE from router/global news alone.
    """
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

    weekend_research = is_weekend_holiday_research_telegram_mode(india)
    if weekend_research:
        return 'RESEARCH_MODE'

    for raw in candidates:
        token = _normalize_mode_token(raw)
        if token == 'INDIA_MODE' or token.startswith('INDIA_'):
            return 'INDIA_MODE'

    code = _normalize_mode_token(india.get('mode_code'))
    label = str(india.get('market_mode') or '').lower()

    if code == MODE_RESEARCH or 'research' in label:
        return 'RESEARCH_MODE'
    if code in _INDIA_MODE_CODES or code.startswith('INDIA') or 'india' in label:
        return 'INDIA_MODE'
    return 'RESEARCH_MODE'


def lock_mode_in_text(text: str, *, resolved_mode: str | None = None) -> str:
    """Replace leaked USA_MODE tokens in formatted Telegram text."""
    mode = resolved_mode or resolve_telegram_market_mode()
    if explicit_usa_mode_configured() and mode == 'USA_MODE':
        return text
    return text.replace('USA_MODE', mode).replace('usa_mode', mode.lower())
