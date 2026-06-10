"""
My Feed suggested_action vocabulary — no direct BUY/SELL (Stage 50F hotfix).
"""

from __future__ import annotations

MYFEED_ALLOWED_SUGGESTED_ACTIONS: tuple[str, ...] = (
    'WATCH FOR CONFIRMATION',
    'MARKET RISK ALERT',
    'COMMODITY RISK ALERT',
    'OIL RISK WATCH',
    'GOLD WATCH',
    'SILVER WATCH',
    'AVOID / RISK WATCH',
    'NEWS ONLY',
    'WAIT FOR CONFIRMATION',
)

MYFEED_ACTIONS_REQUIRING_CONFIRMATION: frozenset[str] = frozenset({
    'WATCH FOR CONFIRMATION',
    'WAIT FOR CONFIRMATION',
    'MARKET RISK ALERT',
    'COMMODITY RISK ALERT',
    'OIL RISK WATCH',
    'GOLD WATCH',
    'SILVER WATCH',
    'AVOID / RISK WATCH',
})

# Block direct trade instructions from vision/classifier output.
_TRADE_TOKENS: tuple[str, ...] = (
    'CONFIRMED BUY',
    'CONFIRMED SELL',
    'BUY NOW',
    'SELL NOW',
    'STRONG BUY',
    'STRONG SELL',
    'BUY_CANDIDATE',
    'SELL_CANDIDATE',
    'BUY',
    'SELL',
)

_ACTION_ALIASES: dict[str, str] = {
    'AVOID': 'AVOID / RISK WATCH',
    'RISK WATCH': 'AVOID / RISK WATCH',
    'RISK ALERT': 'MARKET RISK ALERT',
    'WAIT': 'WAIT FOR CONFIRMATION',
}


def contains_trade_action_literal(text: str) -> bool:
    upper = str(text or '').upper()
    if not upper:
        return False
    for token in _TRADE_TOKENS:
        if token in upper:
            return True
    return False


def normalize_myfeed_suggested_action(value: str, *, fallback: str = 'NEWS ONLY') -> str:
    """Map classifier/vision output to allowed My Feed actions only."""
    raw = str(value or '').strip()
    if not raw:
        return fallback if fallback in MYFEED_ALLOWED_SUGGESTED_ACTIONS else 'NEWS ONLY'

    if contains_trade_action_literal(raw):
        upper = raw.upper()
        if any(w in upper for w in ('AVOID', 'FRAUD', 'DEFAULT', 'DOWNGRADE', 'RISK', 'WEAK', 'FALL', 'DROP')):
            return 'AVOID / RISK WATCH'
        return 'WATCH FOR CONFIRMATION'

    upper = raw.upper()
    if upper in MYFEED_ALLOWED_SUGGESTED_ACTIONS:
        return upper

    if upper in _ACTION_ALIASES:
        return _ACTION_ALIASES[upper]

    for allowed in MYFEED_ALLOWED_SUGGESTED_ACTIONS:
        if allowed in upper:
            return allowed

    safe_fallback = fallback if fallback in MYFEED_ALLOWED_SUGGESTED_ACTIONS else 'NEWS ONLY'
    return safe_fallback


def myfeed_action_options_for_prompt() -> str:
    return '|'.join(MYFEED_ALLOWED_SUGGESTED_ACTIONS)
