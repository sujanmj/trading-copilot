"""
Regime normalization — internal keys never exposed raw to UI/Telegram.

Internal: panic_volatile, volatility_expansion, risk_off, trend_expansion
Display: Panic Volatile, Volatility Expansion, Risk-Off, Trend Expansion
"""

from __future__ import annotations

from typing import Any, Dict, Optional

INTERNAL_REGIMES = frozenset({
    'panic_volatile',
    'volatility_expansion',
    'risk_off',
    'trend_expansion',
    'macro_uncertainty',
    'regime_transition',
    'sideways_chop',
    'sideways',
    'bullish_trend',
    'bearish_trend',
})

_DISPLAY_MAP = {
    'panic_volatile': 'Panic Volatile',
    'volatility_expansion': 'Volatility Expansion',
    'risk_off': 'Risk-Off',
    'trend_expansion': 'Trend Expansion',
    'macro_uncertainty': 'Macro Uncertainty',
    'regime_transition': 'Regime Transition',
    'sideways_chop': 'Range-Bound',
    'sideways': 'Range-Bound',
    'bullish_trend': 'Trend Expansion',
    'bearish_trend': 'Risk-Off',
    'risk_on': 'Trend Expansion',
    'risk-on': 'Trend Expansion',
}

_LEGACY_ALIASES = {
    'panic': 'panic_volatile',
    'volatile': 'volatility_expansion',
    'macro uncertainty': 'macro_uncertainty',
    'regime transition': 'regime_transition',
    'sideways': 'sideways_chop',
    'bullish trend': 'bullish_trend',
    'bearish trend': 'bearish_trend',
}


def normalize_regime_key(raw: Optional[str]) -> str:
    """Map arbitrary regime text to canonical internal key."""
    if not raw:
        return ''
    key = str(raw).strip().lower().replace('-', '_').replace(' ', '_')
    if key in _DISPLAY_MAP:
        return key
    alias = _LEGACY_ALIASES.get(str(raw).strip().lower())
    if alias:
        return alias
    for internal in INTERNAL_REGIMES:
        if internal in key or key in internal:
            return internal
    return key


def display_regime(raw: Optional[str], *, fallback: str = 'Monitoring regime formation') -> str:
    """Human display label — never expose raw enum to UI."""
    if not raw or str(raw).strip().lower() in ('none', 'unknown', 'null', ''):
        return fallback
    internal = normalize_regime_key(raw)
    label = _DISPLAY_MAP.get(internal)
    if label:
        return label
    cleaned = str(raw).replace('_', ' ').strip()
    if cleaned.lower() in ('unknown', 'none'):
        return fallback
    return cleaned.title()


def normalize_regime_payload(payload: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Attach display_regime alongside internal key on a dict."""
    payload = dict(payload or {})
    internal = normalize_regime_key(payload.get('regime') or payload.get('primary_regime') or payload.get('market_regime'))
    if internal:
        payload['regime_internal'] = internal
        payload['regime_display'] = display_regime(internal)
    else:
        payload['regime_display'] = display_regime(None)
    return payload
