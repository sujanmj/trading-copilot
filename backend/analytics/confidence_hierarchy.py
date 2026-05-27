"""
Unified confidence hierarchy — one display label across Telegram, GUI, and exports.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

WATCH_LEVELS = frozenset({'LOW', 'MEDIUM', 'HIGH'})


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def normalize_macro_confidence(raw: Any) -> float:
    """Macro confidence on 0–10 scale."""
    if raw is None:
        return 5.0
    if isinstance(raw, str):
        key = raw.strip().upper()
        band = {'ULTRA': 9.0, 'HIGH': 7.5, 'MEDIUM': 5.0, 'LOW': 3.0, 'WATCH': 2.0}
        if key in band:
            return band[key]
        try:
            val = float(key)
            if val <= 1.0:
                return val * 10.0
            return _clamp(val, 0.0, 10.0)
        except ValueError:
            return 5.0
    try:
        val = float(raw)
        if val <= 1.0:
            return val * 10.0
        return _clamp(val, 0.0, 10.0)
    except (TypeError, ValueError):
        return 5.0


def normalize_ml_probability(raw: Any) -> Optional[float]:
    """ML probability 0–100%."""
    if raw is None:
        return None
    try:
        val = float(raw)
        if val <= 1.0:
            val *= 100.0
        return round(_clamp(val, 0.0, 100.0), 1)
    except (TypeError, ValueError):
        return None


def normalize_watch_conviction(raw: Any, *, rank_score: Optional[float] = None) -> str:
    if isinstance(raw, str) and raw.strip().upper() in WATCH_LEVELS:
        return raw.strip().upper()
    if rank_score is not None:
        if rank_score >= 8.0:
            return 'HIGH'
        if rank_score >= 5.5:
            return 'MEDIUM'
        return 'LOW'
    return 'MEDIUM'


def normalize_regime_stability(raw: Any) -> float:
    try:
        val = float(raw)
        if val > 1.0 and val <= 10.0:
            val /= 10.0
        return round(_clamp(val, 0.0, 1.0), 2)
    except (TypeError, ValueError):
        return 0.5


def normalize_quality_iq(raw: Any) -> float:
    try:
        val = float(raw)
        if val > 1.0 and val <= 100.0:
            val /= 100.0
        return round(_clamp(val, 0.0, 1.0), 2)
    except (TypeError, ValueError):
        return 0.5


def normalize_confidence(context: dict) -> Dict[str, Any]:
    """
    Build hierarchical confidence view from mixed upstream fields.
    Precedence: elite ML > macro mood > rank score > raw band.
    """
    ctx = context if isinstance(context, dict) else {}
    ml = normalize_ml_probability(ctx.get('ml_confidence') or ctx.get('ml_probability'))
    macro = normalize_macro_confidence(
        ctx.get('macro_confidence') or ctx.get('confidence_level') or ctx.get('confidence')
    )
    watch_conv = normalize_watch_conviction(
        ctx.get('elite_conviction') or ctx.get('conviction'),
        rank_score=ctx.get('_rank_score') or ctx.get('rank_score'),
    )
    regime = normalize_regime_stability(ctx.get('regime_stability') or ctx.get('regime_persistence'))
    quality = normalize_quality_iq(ctx.get('quality_iq') or ctx.get('quality_score'))
    tier = str(ctx.get('display_tier') or '').upper()

    if ml is not None and ml >= 72 and ctx.get('elite_verified') and tier == 'ELITE':
        display = f'High Conviction {ml:.0f}%'
        source = 'ml_elite'
    elif ml is not None and ml >= 55:
        display = f'ML {ml:.0f}%'
        source = 'ml_probability'
    elif macro >= 7.5:
        display = f'MACRO {macro:.1f}/10'
        source = 'macro'
    elif tier == 'AVOID':
        display = 'AVOID'
        source = 'avoid'
    else:
        display = format_signal_status_line({'display_tier': tier, 'display_confidence': watch_conv})
        source = 'watch'

    return {
        'macro_confidence': round(macro, 1),
        'ml_probability_pct': ml,
        'watch_conviction': watch_conv,
        'regime_stability': regime,
        'quality_iq': quality,
        'display_label': display,
        'source': source,
    }
