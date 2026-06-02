"""
Elite trade planner — ATR/volatility-based levels for ML-validated ELITE setups only.
WATCH and AVOID tiers never receive execution levels from this module.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

MIN_RR = 1.5
MIN_VOLUME_RATIO = 0.8


def _estimate_atr(price: float, change_pct: float, volume_ratio: float) -> float:
    vol_pct = max(0.6, min(6.0, abs(change_pct) * 0.35 + max(1.0, volume_ratio) * 0.25))
    return price * vol_pct / 100.0


def build_elite_plan(
    item: dict,
    *,
    scanner_row: Optional[dict] = None,
    sector_strength: float = 0.5,
) -> Optional[Dict[str, Any]]:
    """Generate entry/SL/targets only when elite execution criteria are met."""
    item = item if isinstance(item, dict) else {}
    if str(item.get('display_tier') or '').upper() != 'ELITE':
        return None
    if not item.get('elite_verified'):
        return None

    scan = scanner_row if isinstance(scanner_row, dict) else {}

    price = float(scan.get('price') or item.get('price') or item.get('last_price') or 0)
    if price <= 0:
        return None

    change_pct = float(scan.get('change_percent') or item.get('change_percent') or 2.0)
    volume_ratio = float(scan.get('volume_ratio') or item.get('volume_ratio') or 1.0)
    atr = _estimate_atr(price, change_pct, volume_ratio)

    entry_low = price - atr * 0.15
    entry_high = price + atr * 0.10
    stop = price - atr * 1.2
    target_1 = price + atr * 2.0
    target_2 = price + atr * 3.2

    risk = max(0.01, price - stop)
    reward = max(0.0, target_1 - price)
    rr = reward / risk if risk else 0.0

    conviction = 'LOW'
    if sector_strength >= 0.75 and volume_ratio >= 2.0:
        conviction = 'HIGH'
    elif sector_strength >= 0.55 or volume_ratio >= 1.2:
        conviction = 'MEDIUM'

    if volume_ratio < MIN_VOLUME_RATIO or rr < MIN_RR:
        return None

    invalidation = f'Close below {stop:.2f} or momentum fades with sector strength < {sector_strength:.0%}'
    why_elite = item.get('confidence_note') or 'Institutional ML + scanner + macro alignment'
    return {
        'entry_range': f'{entry_low:.2f}-{entry_high:.2f}',
        'stop_loss': round(stop, 2),
        'target_1': round(target_1, 2),
        'target_2': round(target_2, 2),
        'target': round(target_1, 2),
        'risk_reward': round(rr, 2),
        'invalidation': invalidation,
        'conviction': conviction,
        'atr': round(atr, 2),
        'tier': 'ELITE',
        'why_elite': why_elite,
    }


def attach_elite_plans(items: list, scanner_index: dict, intel: dict) -> list:
    """Attach elite_plan + normalized levels to ELITE-tier items only."""
    sectors = (intel.get('sector_rotation') or {}) if isinstance(intel, dict) else {}
    bullish = {str(s).upper() for s in (sectors.get('bullish') or [])}
    out = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        enriched = dict(item)
        if str(enriched.get('display_tier') or '').upper() != 'ELITE':
            enriched.pop('entry_zone', None)
            enriched.pop('target', None)
            enriched.pop('stop_loss', None)
            enriched.pop('target_2', None)
            enriched.pop('risk_reward', None)
            out.append(enriched)
            continue
        sym = str(enriched.get('symbol') or '').upper()
        sector = str(enriched.get('sector') or '').upper()
        sector_strength = 0.85 if sector in bullish or sym in bullish else 0.45
        plan = build_elite_plan(
            enriched,
            scanner_row=(scanner_index or {}).get(sym),
            sector_strength=sector_strength,
        )
        if plan:
            enriched['elite_plan'] = plan
            enriched['entry_zone'] = plan.get('entry_range')
            enriched['stop_loss'] = plan.get('stop_loss')
            enriched['target'] = plan.get('target_1')
            enriched['target_2'] = plan.get('target_2')
            enriched['risk_reward'] = plan.get('risk_reward')
            enriched['invalidation'] = plan.get('invalidation')
            enriched['why_elite'] = plan.get('why_elite')
            enriched['elite_conviction'] = plan.get('conviction')
        out.append(enriched)
    return out
