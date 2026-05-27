"""
Signal quality engine — prevent scanner hype from masquerading as elite conviction.
"""

from __future__ import annotations

from typing import Any, Dict, Optional


def _volatility_regime(ctx: dict) -> str:
    vix = float(ctx.get('volatility_index') or ctx.get('vix') or 0)
    if vix >= 25:
        return 'HIGH'
    if vix >= 18:
        return 'ELEVATED'
    return 'NORMAL'


def assess_signal_quality(item: dict, *, ctx: Optional[dict] = None, scanner_row: Optional[dict] = None) -> Dict[str, Any]:
    """
    Rules:
    - High-conviction scanner ≠ elite trade
    - strong momentum without ML confirmation = watch only
    - volatility regime reduces confidence automatically
    """
    ctx = ctx or {}
    item = item if isinstance(item, dict) else {}
    scan = scanner_row if isinstance(scanner_row, dict) else {}

    strength = str(scan.get('strength') or item.get('strength') or '').upper()
    ml = item.get('ml_confidence')
    try:
        ml_val = float(ml) if ml is not None else None
        if ml_val is not None and ml_val <= 1:
            ml_val *= 100
    except (TypeError, ValueError):
        ml_val = None

    elite_verified = bool(item.get('elite_verified'))
    regime = _volatility_regime(ctx)
    quality_score = 0.55
    tier_cap = 'ELITE'
    notes = []

    from backend.intelligence.institutional_language import is_high_conviction_strength
    if is_high_conviction_strength(strength) and not elite_verified:
        tier_cap = 'WATCH'
        quality_score -= 0.15
        notes.append('High-conviction scanner momentum — watch only until ML confirms')

    if ml_val is None or ml_val < 72:
        if tier_cap == 'ELITE':
            tier_cap = 'WATCH'
        quality_score -= 0.1
        if ml_val is not None:
            notes.append(f'ML {ml_val:.0f}% below elite threshold (72%)')
        else:
            notes.append('No institutional ML confirmation')

    if regime == 'HIGH':
        quality_score -= 0.2
        tier_cap = 'WATCH' if tier_cap == 'ELITE' else tier_cap
        notes.append('High volatility regime — confidence reduced')
    elif regime == 'ELEVATED':
        quality_score -= 0.1
        notes.append('Elevated volatility — size down')

    change = abs(float(scan.get('change_percent') or item.get('change_percent') or 0))
    vol_ratio = float(scan.get('volume_ratio') or item.get('volume_ratio') or 1)
    if change >= 8 and vol_ratio >= 3 and not elite_verified:
        tier_cap = 'WATCH'
        notes.append('Parabolic move — hype risk, not elite conviction')

    quality_score = max(0.1, min(1.0, quality_score))
    return {
        'quality_score': round(quality_score, 2),
        'tier_cap': tier_cap,
        'allow_full_levels': tier_cap == 'ELITE' and elite_verified,
        'allow_high_conviction_alert': tier_cap == 'ELITE' and elite_verified and quality_score >= 0.7,
        'quality_notes': notes,
        'volatility_regime': regime,
    }


def apply_signal_quality(item: dict, quality: dict) -> dict:
    out = dict(item)
    out['signal_quality'] = quality
    out['quality_score'] = quality.get('quality_score')
    if quality.get('tier_cap') == 'WATCH' and out.get('display_tier') == 'ELITE':
        out['display_tier'] = 'WATCH'
        out['elite_verified'] = False
    if not quality.get('allow_full_levels'):
        out['suppress_elite_levels'] = True
        for key in ('entry_zone', 'target', 'stop_loss', 'target_2', 'risk_reward'):
            out.pop(key, None)
    if quality.get('quality_notes'):
        out['confidence_note'] = '; '.join(quality['quality_notes'][:2])
    return out
